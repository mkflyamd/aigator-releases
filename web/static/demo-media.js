/* Demo clip intake: validation helpers, XHR upload and the clip panel. Plain global script. */
const DemoMedia = (() => {
  const VIDEO_EXTS = ['mp4', 'mov', 'm4v', 'webm'];
  const AUDIO_EXTS = ['mp3', 'm4a', 'wav', 'aac', 'ogg', 'flac'];
  const MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024;
  const MIN_CLIP_SECONDS = 0.5;
  const POLL_MS = 2000;
  const BASE = '/api/demo-media';

  let currentProjectId = null;
  let registry = null;
  let panelEl = null;
  let pollTimer = null;
  let statusText = '';

  function classify(name) {
    const m = /\.([^.\\/]+)$/.exec(String(name || ''));
    if (!m) return null;
    const ext = m[1].toLowerCase();
    if (VIDEO_EXTS.includes(ext)) return 'video';
    if (AUDIO_EXTS.includes(ext)) return 'audio';
    return null;
  }

  function validateLocal(file) {
    if (!file.size) return 'File is empty';
    if (file.size > MAX_FILE_BYTES) return 'File exceeds the 2 GB limit';
    return null;
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    return Math.floor(total / 60) + ':' + String(total % 60).padStart(2, '0');
  }

  function parseTrim(startText, endText, duration) {
    const s = String(startText == null ? '' : startText).trim();
    const e = String(endText == null ? '' : endText).trim();
    const start = s === '' ? 0 : Number(s);
    const end = e === '' ? null : Number(e);
    if (!Number.isFinite(start) || start < 0) {
      return { ok: false, error: 'Start must be 0 or more seconds' };
    }
    if (end !== null && !Number.isFinite(end)) {
      return { ok: false, error: 'End must be a number of seconds' };
    }
    const effectiveEnd = end === null ? duration : end;
    if (effectiveEnd > duration + 0.001) {
      return { ok: false, error: 'End is past the end of the clip' };
    }
    if (effectiveEnd - start < MIN_CLIP_SECONDS) {
      return { ok: false, error: 'Keep at least ' + MIN_CLIP_SECONDS + ' seconds of the clip' };
    }
    return { ok: true, trim_start: start, trim_end: end };
  }

  function moveId(ids, id, delta) {
    const out = ids.slice();
    const from = out.indexOf(id);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= out.length) return out;
    out.splice(from, 1);
    out.splice(to, 0, id);
    return out;
  }

  function errorMessage(body, status) {
    return (body && (body.message || body.detail)) || 'Request failed (' + status + ')';
  }

  function upload(file, opts) {
    const o = opts || {};
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      let url = BASE + '/upload?filename=' + encodeURIComponent(file.name);
      if (o.projectId) url += '&project_id=' + encodeURIComponent(o.projectId);
      xhr.open('POST', url);
      xhr.setRequestHeader('Content-Type', 'application/octet-stream');
      xhr.setRequestHeader('X-CSRF-Token', window.__CSRF_TOKEN__ || '');
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable && o.onProgress) o.onProgress(Math.round((ev.loaded * 100) / ev.total));
      };
      xhr.onerror = () => reject(new Error('Upload failed: connection error'));
      xhr.onabort = () => {
        const err = new Error('Upload cancelled');
        err.name = 'AbortError';
        reject(err);
      };
      xhr.onload = () => {
        let body = null;
        try {
          body = JSON.parse(xhr.responseText);
        } catch (_) {
          body = null;
        }
        if (xhr.status >= 200 && xhr.status < 300 && body && body.ok) resolve(body);
        else reject(new Error(errorMessage(body, xhr.status)));
      };
      xhr.send(file);
      if (o.signal) {
        if (o.signal.aborted) xhr.abort();
        else o.signal.addEventListener('abort', () => xhr.abort());
      }
    });
  }

  async function call(method, path, body) {
    const init = { method, headers: {} };
    if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    const res = await fetch(BASE + '/' + path, init);
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      data = null;
    }
    if (!res.ok || !data || !data.ok) throw new Error(errorMessage(data, res.status));
    return data;
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function iconButton(label, title, disabled, onClick) {
    const b = el('button', 'demo-media-btn', label);
    b.type = 'button';
    b.title = title;
    b.setAttribute('aria-label', title);
    b.disabled = !!disabled;
    b.addEventListener('click', onClick);
    return b;
  }

  function summary(reg) {
    if (!reg.clips.length) return reg.audio.length ? 'Add a video clip to build the timeline' : 'No clips yet';
    const tl = reg.timeline || {};
    if (tl.state === 'ready') return 'Ready - ' + formatDuration(tl.duration) + ' total';
    if (tl.state === 'failed') return 'Build failed: ' + (tl.error || 'unknown error');
    return 'Building timeline...';
  }

  function needsPoll() {
    if (!registry || !registry.clips.length) return false;
    const state = (registry.timeline || {}).state;
    return state !== 'ready' && state !== 'failed';
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    pollTimer = null;
    if (!needsPoll() || !currentProjectId) return;
    const pid = currentProjectId;
    pollTimer = setTimeout(async () => {
      try {
        const data = await call('GET', encodeURIComponent(pid));
        if (pid === currentProjectId) {
          const changed = JSON.stringify(data.clips) !== JSON.stringify(registry);
          registry = data.clips;
          if (changed) render();
        }
      } catch (e) {
        statusText = e.message;
        render();
        return;
      }
      schedulePoll();
    }, POLL_MS);
  }

  async function mutate(method, path, body) {
    try {
      const data = await call(method, encodeURIComponent(currentProjectId) + '/' + path, body);
      registry = data.clips;
      statusText = '';
    } catch (e) {
      statusText = e.message;
    }
    render();
    schedulePoll();
  }

  function clipRow(clip, ids) {
    const row = el('div', 'demo-media-row');
    row.appendChild(el('span', 'demo-media-name', clip.name));
    row.appendChild(el('span', 'demo-media-dur', formatDuration(clip.duration)));
    const i = ids.indexOf(clip.id);
    row.appendChild(iconButton('↑', 'Move ' + clip.name + ' earlier', i === 0, () =>
      mutate('PUT', 'order', { ids: moveId(ids, clip.id, -1) })));
    row.appendChild(iconButton('↓', 'Move ' + clip.name + ' later', i === ids.length - 1, () =>
      mutate('PUT', 'order', { ids: moveId(ids, clip.id, 1) })));
    const start = el('input', 'demo-media-trim');
    start.type = 'text';
    start.value = String(clip.trim_start || 0);
    start.setAttribute('aria-label', 'Trim start seconds for ' + clip.name);
    const end = el('input', 'demo-media-trim');
    end.type = 'text';
    end.value = clip.trim_end == null ? '' : String(clip.trim_end);
    end.placeholder = 'end';
    end.setAttribute('aria-label', 'Trim end seconds for ' + clip.name);
    const applyTrim = () => {
      const t = parseTrim(start.value, end.value, clip.duration);
      if (!t.ok) {
        statusText = t.error;
        render();
        return;
      }
      mutate('PATCH', 'clips/' + encodeURIComponent(clip.id), {
        trim_start: t.trim_start,
        trim_end: t.trim_end,
      });
    };
    start.addEventListener('change', applyTrim);
    end.addEventListener('change', applyTrim);
    row.appendChild(start);
    row.appendChild(end);
    row.appendChild(removeButton(clip));
    return row;
  }

  function removeButton(item) {
    return iconButton('✕', 'Remove ' + item.name, false, () =>
      mutate('DELETE', 'items/' + encodeURIComponent(item.id)));
  }

  function audioRow(asset) {
    const row = el('div', 'demo-media-row demo-media-audio');
    row.appendChild(el('span', 'demo-media-name', '🎵 ' + asset.name));
    row.appendChild(el('span', 'demo-media-dur', formatDuration(asset.duration)));
    row.appendChild(removeButton(asset));
    return row;
  }

  function render() {
    if (!panelEl) return;
    panelEl.textContent = '';
    const has = registry && (registry.clips.length || registry.audio.length);
    panelEl.classList.toggle('hidden', !has);
    if (!has) return;
    const state = (registry.timeline || {}).state;
    const label = el('div', 'demo-media-state demo-media-' + (registry.clips.length ? state : 'idle'), summary(registry));
    label.setAttribute('role', 'status');
    panelEl.appendChild(label);
    const ids = registry.clips.map((c) => c.id);
    registry.clips.forEach((clip) => panelEl.appendChild(clipRow(clip, ids)));
    registry.audio.forEach((asset) => panelEl.appendChild(audioRow(asset)));
    if (statusText) {
      const err = el('div', 'demo-media-error', statusText);
      err.setAttribute('role', 'alert');
      panelEl.appendChild(err);
    }
  }

  function setProject(projectId, reg) {
    currentProjectId = projectId;
    registry = reg;
    statusText = '';
    render();
    schedulePoll();
  }

  function mountPanel(container) {
    panelEl = container;
    render();
  }

  return {
    classify,
    validateLocal,
    formatDuration,
    parseTrim,
    moveId,
    upload,
    setProject,
    mountPanel,
    get currentProjectId() {
      return currentProjectId;
    },
  };
})();
