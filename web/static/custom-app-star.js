// Renderer side of the address bar star: adds, renames and removes custom apps on behalf of the
// toolbar, with an Undo window before a removal becomes permanent. The controller takes its
// dependencies as arguments so Node tests can drive it without a DOM.
(function (root) {
  'use strict';

  const UNDO_MS = 8000;

  function createStarController(deps) {
    const { api, shell, ui } = deps;
    const undoMs = deps.undoMs || UNDO_MS;
    let pending = null;

    async function commitPending() {
      if (!pending) return;
      const { app, toast } = pending;
      pending = null;
      toast.dismiss();
      try {
        await api.remove(app.id);
        await shell.customAppTeardown(app.id);
      } catch {
        // The app stays in config; it comes back on the next launch instead of being lost silently.
      }
      ui.reloadList();
    }

    function undoPending() {
      if (!pending) return;
      const { app, toast } = pending;
      pending = null;
      toast.dismiss();
      shell.customAppSetHidden(app.id, false);
      ui.registerApp(app);
    }

    async function add({ url, name }) {
      await commitPending();
      const app = await api.create(name, url);
      await shell.createCustomApp(app);
      ui.registerApp(app);
      ui.reloadList();
      ui.showApp(app.id);
      const toast = ui.toast({
        message: 'Added to Gator apps',
        actions: [{ label: 'Undo', run: () => removeNow(app) }],
        ms: undoMs,
      });
      return { app, toast };
    }

    async function removeNow(app) {
      await shell.customAppSetHidden(app.id, true);
      ui.closeIfActive(app.id);
      ui.unregisterApp(app.id);
      await api.remove(app.id);
      await shell.customAppTeardown(app.id);
      ui.reloadList();
    }

    async function rename(appId, name) {
      const app = await api.rename(appId, name);
      ui.relabelApp(appId, app.name);
      ui.reloadList();
    }

    async function remove(appId) {
      await commitPending();
      const app = ui.getApp(appId);
      if (!app) return;
      await shell.customAppSetHidden(appId, true);
      ui.closeIfActive(appId);
      ui.unregisterApp(appId);
      const toast = ui.toast({
        message: `Removed ${app.name} from Gator apps`,
        actions: [{ label: 'Undo', run: undoPending }],
        ms: undoMs,
        onExpire: commitPending,
      });
      pending = { app, toast };
    }

    function handle(event) {
      if (!event) return Promise.resolve();
      if (event.kind === 'add') return add({ url: event.url, name: event.name });
      if (event.kind === 'rename') return rename(event.appId, event.name);
      if (event.kind === 'remove') return remove(event.appId);
      return Promise.resolve();
    }

    return { handle, commitPending, hasPending: () => !!pending };
  }

  const api = { UNDO_MS, createStarController };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;

  function showToast({ message, actions, ms, onExpire }) {
    let host = document.getElementById('gator-toast-host');
    if (!host) {
      host = document.createElement('div');
      host.id = 'gator-toast-host';
      document.body.appendChild(host);
    }
    const el = document.createElement('div');
    el.className = 'gator-toast';
    el.setAttribute('role', 'status');
    const text = document.createElement('span');
    text.className = 'gator-toast-text';
    text.textContent = message;
    el.appendChild(text);

    let timer = null;
    let done = false;
    const dismiss = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      el.classList.remove('is-in');
      setTimeout(() => el.remove(), 200);
    };
    const arm = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        dismiss();
        if (onExpire) onExpire();
      }, ms);
    };
    for (const a of actions) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'gator-toast-action';
      b.textContent = a.label;
      b.addEventListener('click', () => {
        dismiss();
        a.run();
      });
      el.appendChild(b);
    }
    el.addEventListener('mouseenter', () => clearTimeout(timer));
    el.addEventListener('mouseleave', arm);
    el.addEventListener('focusin', () => clearTimeout(timer));
    el.addEventListener('focusout', arm);
    host.appendChild(el);
    requestAnimationFrame(() => el.classList.add('is-in'));
    arm();
    return { dismiss };
  }

  const customApps = new Map();

  function appFromList(id) {
    return customApps.get(id) || null;
  }

  const ui = {
    registerApp(app) {
      customApps.set(app.id, app);
      _registerCustomAppSkill(app);
    },
    unregisterApp(id) {
      const idx = SKILL_REGISTRY.findIndex((s) => s.id === id);
      if (idx >= 0) SKILL_REGISTRY.splice(idx, 1);
      delete SKILL_MAP[id];
      renderDock();
    },
    relabelApp(id, name) {
      const entry = SKILL_MAP[id];
      if (entry) entry.label = name;
      const cached = customApps.get(id);
      if (cached) cached.name = name;
      renderDock();
    },
    getApp(id) {
      const entry = SKILL_MAP[id];
      if (!entry) return null;
      return appFromList(id) || { id, name: entry.label, url: entry._customAppUrl };
    },
    closeIfActive(id) {
      if (typeof tpState !== 'undefined' && tpState.type === id) closeThirdPane();
    },
    showApp(id) {
      openThirdPane(id);
    },
    reloadList() {
      return _loadCustomApps();
    },
    toast: showToast,
  };

  const controller = createStarController({
    api: {
      async create(name, url) {
        const res = await fetch('/api/config/custom-apps', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, url }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to add app');
        return data.app;
      },
      async rename(id, name) {
        const res = await fetch(`/api/config/custom-apps/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to rename app');
        return data.app;
      },
      async remove(id) {
        const res = await fetch(`/api/config/custom-apps/${encodeURIComponent(id)}`, {
          method: 'DELETE',
          keepalive: true,
        });
        if (!res.ok) throw new Error('Failed to remove app');
      },
    },
    shell: root.gatorShell || {},
    ui,
  });

  root.CustomAppStar = Object.assign(api, { controller });

  const shell = root.gatorShell;
  if (shell && shell.isShell && shell.onCustomAppStar) {
    shell.onCustomAppStar((event) => {
      controller.handle(event).catch((e) => {
        if (typeof _showConnectivityToast === 'function') {
          _showConnectivityToast(e.message || 'Could not update Gator apps.', 'warning');
        }
      });
    });
  }
  root.addEventListener('beforeunload', () => {
    controller.commitPending();
  });
})(typeof window !== 'undefined' ? window : globalThis);
