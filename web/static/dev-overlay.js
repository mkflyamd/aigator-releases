/* -- Always-On dev overlay (Ctrl+Shift+Alt+K) --
 * DEV BUILD ONLY -- not included in distribution.
 * Simulates mouse activity to prevent sleep / idle status.
 */
(function() {
  let _aoTimer = null;
  let _aoMinutes = 2;
  let _aoUnlocked = false;

  document.addEventListener('keydown', e => {
    if (e.ctrlKey && e.shiftKey && e.altKey && e.key === 'K') {
      e.preventDefault();
      if (!_aoUnlocked) { _aoShowAuth(); } else { _aoShowPanel(); }
    }
  });

  function _aoShowAuth() {
    const overlay = document.createElement('div');
    overlay.id = 'ao-overlay';
    Object.assign(overlay.style, {
      position:'fixed', inset:'0', zIndex:'99999',
      display:'flex', alignItems:'center', justifyContent:'center',
      background:'rgba(0,0,0,.7)', backdropFilter:'blur(6px)',
    });
    overlay.innerHTML = `
      <div style="background:var(--surface,#1e293b);border-radius:12px;padding:1.5rem 2rem;min-width:280px;display:flex;flex-direction:column;gap:.8rem;box-shadow:0 8px 32px rgba(0,0,0,.5)">
        <div style="font-size:.85rem;font-weight:700;color:var(--text,#e2e8f0)">Authenticate</div>
        <input id="ao-pass" type="password" placeholder="Enter password" style="padding:.45rem .6rem;border-radius:6px;border:1px solid var(--border,#334155);background:var(--bg-1,#0f172a);color:var(--text);font-size:.82rem;outline:none" autocomplete="off" />
        <div id="ao-err" style="font-size:.72rem;color:#f87171;display:none"></div>
        <div style="display:flex;gap:.5rem;justify-content:flex-end">
          <button id="ao-cancel" style="padding:.35rem .7rem;border:1px solid var(--border);border-radius:6px;background:none;color:var(--text-sub);cursor:pointer;font-size:.78rem">Cancel</button>
          <button id="ao-ok" style="padding:.35rem .7rem;border:none;border-radius:6px;background:var(--accent,#6c63ff);color:#fff;cursor:pointer;font-size:.78rem;font-weight:600">Unlock</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const passInput = overlay.querySelector('#ao-pass');
    passInput.focus();
    overlay.querySelector('#ao-cancel').addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
    function tryUnlock() {
      if (passInput.value === 'maykulka') {
        _aoUnlocked = true;
        overlay.remove();
        _aoShowPanel();
      } else {
        const err = overlay.querySelector('#ao-err');
        err.textContent = 'Incorrect password';
        err.style.display = 'block';
        passInput.value = '';
        passInput.focus();
      }
    }
    overlay.querySelector('#ao-ok').addEventListener('click', tryUnlock);
    passInput.addEventListener('keydown', e => { if (e.key === 'Enter') tryUnlock(); });
  }

  function _aoShowPanel() {
    document.getElementById('ao-overlay')?.remove();
    const isActive = !!_aoTimer;
    const overlay = document.createElement('div');
    overlay.id = 'ao-overlay';
    Object.assign(overlay.style, {
      position:'fixed', inset:'0', zIndex:'99999',
      display:'flex', alignItems:'center', justifyContent:'center',
      background:'rgba(0,0,0,.7)', backdropFilter:'blur(6px)',
    });
    overlay.innerHTML = `
      <div style="background:var(--surface,#1e293b);border-radius:12px;padding:1.5rem 2rem;min-width:300px;display:flex;flex-direction:column;gap:.8rem;box-shadow:0 8px 32px rgba(0,0,0,.5)">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div style="font-size:.9rem;font-weight:700;color:var(--text,#e2e8f0)">Always On</div>
          <div id="ao-status" style="font-size:.7rem;padding:.2rem .5rem;border-radius:10px;font-weight:600;${isActive ? 'background:#16a34a;color:#fff' : 'background:var(--bg-1,#0f172a);color:var(--text-sub)'}">${isActive ? 'ACTIVE' : 'OFF'}</div>
        </div>
        <div style="font-size:.74rem;color:var(--text-sub,#94a3b8);line-height:1.4">Prevents sleep and idle status by simulating activity at regular intervals.</div>
        <div style="display:flex;align-items:center;gap:.6rem">
          <label style="font-size:.78rem;color:var(--text-sub)">Interval</label>
          <select id="ao-interval" style="padding:.3rem .5rem;border-radius:6px;border:1px solid var(--border,#334155);background:var(--bg-1,#0f172a);color:var(--text);font-size:.78rem">
            <option value="1" ${_aoMinutes===1?'selected':''}>1 min</option>
            <option value="2" ${_aoMinutes===2?'selected':''}>2 min</option>
            <option value="3" ${_aoMinutes===3?'selected':''}>3 min</option>
            <option value="5" ${_aoMinutes===5?'selected':''}>5 min</option>
            <option value="10" ${_aoMinutes===10?'selected':''}>10 min</option>
          </select>
        </div>
        <div style="display:flex;gap:.5rem;justify-content:flex-end;margin-top:.3rem">
          <button id="ao-close" style="padding:.35rem .7rem;border:1px solid var(--border);border-radius:6px;background:none;color:var(--text-sub);cursor:pointer;font-size:.78rem">Close</button>
          <button id="ao-toggle" style="padding:.35rem .8rem;border:none;border-radius:6px;color:#fff;cursor:pointer;font-size:.78rem;font-weight:600;background:${isActive ? '#dc2626' : '#16a34a'}">${isActive ? 'Stop' : 'Start'}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
    overlay.querySelector('#ao-close').addEventListener('click', () => overlay.remove());
    overlay.querySelector('#ao-interval').addEventListener('change', e => {
      _aoMinutes = parseInt(e.target.value);
      if (_aoTimer) { _aoStop(); _aoStart(); _aoShowPanel(); }
    });
    overlay.querySelector('#ao-toggle').addEventListener('click', () => {
      if (_aoTimer) { _aoStop(); } else { _aoStart(); }
      overlay.remove();
      _aoShowPanel();
    });
  }

  function _aoStart() {
    if (_aoTimer) return;
    _aoJiggle();
    _aoTimer = setInterval(_aoJiggle, _aoMinutes * 60 * 1000);
  }

  function _aoStop() {
    if (_aoTimer) { clearInterval(_aoTimer); _aoTimer = null; }
  }

  function _aoJiggle() {
    fetch('/api/keepalive/jiggle', { method: 'POST' }).catch(() => {});
  }
})();