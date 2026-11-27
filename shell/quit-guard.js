// Quitting while commands run on the user's computer asks once, then stops them.
function quitCopy(count) {
  const one = count === 1;
  return {
    title: 'Quit AI Gator?',
    message: `Quit and stop ${count} running command${one ? '' : 's'}?`,
    detail: `${one ? '1 command is' : `${count} commands are`} still running on this computer. Quitting stops ${one ? 'it' : 'them'}.`,
    buttons: ['Quit and stop', 'Cancel'],
    defaultId: 1,
    cancelId: 1,
  };
}

async function runningCount(backendRequest) {
  try {
    const status = await backendRequest('GET', '/api/host-shell/status', { timeoutMs: 1500 });
    return Array.isArray(status && status.running) ? status.running.length : 0;
  } catch {
    return 0;
  }
}

async function stopAll(backendRequest) {
  try {
    const { csrf_token } = await backendRequest('GET', '/api/csrf');
    await backendRequest('POST', '/api/host-shell/stop-all', {
      headers: { 'X-CSRF-Token': csrf_token },
      body: {},
      timeoutMs: 5000,
    });
  } catch {}
}

// Resolves true when the app may quit. Commands are stopped before it does.
async function confirmQuit({ backendRequest, showConfirm }) {
  const count = await runningCount(backendRequest);
  if (count === 0) return true;
  const { response } = await showConfirm(quitCopy(count));
  if (response !== 0) return false;
  await stopAll(backendRequest);
  return true;
}

module.exports = { confirmQuit, quitCopy };
