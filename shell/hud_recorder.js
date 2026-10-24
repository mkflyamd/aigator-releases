'use strict';

// Recorder actions a floating HUD widget may ask the shell to run. Widget HTML is
// model-written, so it never holds the backend CSRF token: the main process makes the
// request, and only after the user has allowed that HUD window in a native dialog.
const HUD_RECORDER_ACTIONS = {
  'select-screen': { screen_index: 'number' },
  'pick-region': { screen_index: 'number' },
  start: {
    screen_index: 'number',
    force: 'boolean',
    crop_x: 'number',
    crop_y: 'number',
    crop_w: 'number',
    crop_h: 'number',
  },
  pause: {},
  resume: {},
  stop: {},
};

const HUD_RECORDER_GRANT_IDLE_MS = 10 * 60 * 1000;

function hudRecorderParams(spec, given) {
  const src = given && typeof given === 'object' ? given : {};
  const out = {};
  for (const [key, type] of Object.entries(spec)) {
    const v = src[key];
    if (v === undefined || v === null) continue;
    if (typeof v !== type || (type === 'number' && !Number.isFinite(v))) return null;
    out[key] = v;
  }
  return out;
}

// confirm(senderId) -> Promise<boolean> shows the native consent dialog.
// request(action, params) -> Promise<object> performs the CSRF-bearing backend call.
function createHudRecorder({
  confirm,
  request,
  now = Date.now,
  idleMs = HUD_RECORDER_GRANT_IDLE_MS,
}) {
  const grants = new Map();
  const pending = new Map();

  function granted(senderId) {
    const until = grants.get(senderId);
    if (!until || now() > until) {
      grants.delete(senderId);
      return false;
    }
    grants.set(senderId, now() + idleMs);
    return true;
  }

  function askOnce(senderId) {
    if (pending.has(senderId)) return pending.get(senderId);
    const p = Promise.resolve()
      .then(() => confirm(senderId))
      .catch(() => false)
      .then((ok) => {
        pending.delete(senderId);
        if (ok === true) grants.set(senderId, now() + idleMs);
        return ok === true;
      });
    pending.set(senderId, p);
    return p;
  }

  async function handle(senderId, action, params) {
    const spec =
      typeof action === 'string' &&
      Object.prototype.hasOwnProperty.call(HUD_RECORDER_ACTIONS, action)
        ? HUD_RECORDER_ACTIONS[action]
        : null;
    if (!spec) return { ok: false, error: 'unknown recorder action' };
    const clean = hudRecorderParams(spec, params);
    if (!clean) return { ok: false, error: 'invalid parameters' };
    if (!granted(senderId) && !(await askOnce(senderId))) {
      return { ok: false, error: 'Screen recording was not allowed for this widget.' };
    }
    try {
      return await request(action, clean);
    } catch (err) {
      return { ok: false, error: String((err && err.message) || err) };
    }
  }

  function forget(senderId) {
    grants.delete(senderId);
  }

  return { handle, forget };
}

module.exports = { HUD_RECORDER_ACTIONS, hudRecorderParams, createHudRecorder };
