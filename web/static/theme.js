const ThemeManager = (() => {
  const LS_KEY = 'gator-theme-effective';
  const VALID = ['system', 'light', 'dark'];
  let _active = 'system';
  let _initialized = false;
  const _osQuery = window.matchMedia('(prefers-color-scheme: dark)');

  function _resolve() {
    if (_active === 'system') return _osQuery.matches ? 'dark' : 'light';
    return _active;
  }

  function _apply(effective) {
    document.documentElement.setAttribute('data-theme', effective);
    try { localStorage.setItem(LS_KEY, effective); } catch (_) {}
  }

  function _syncUI() {
    const subEl = document.getElementById('theme-sub');
    if (subEl) {
      subEl.textContent = _active === 'system' ? 'System (OS default)'
                        : _active === 'light'  ? 'Light'
                        : 'Dark';
    }
    VALID.forEach(val => {
      const tile = document.getElementById('theme-tile-' + val);
      if (tile) tile.classList.toggle('active', val === _active);
    });
  }

  function init() {
    if (_initialized) return;
    _initialized = true;

    fetch('/api/config')
      .then(r => r.json())
      .then(cfg => {
        _active = VALID.includes(cfg.theme) ? cfg.theme : 'system';
        _apply(_resolve());
        _syncUI();
      })
      .catch(() => { _syncUI(); });

    _osQuery.addEventListener('change', () => {
      if (_active === 'system') _apply(_resolve());
    });
  }

  function set(value) {
    if (!VALID.includes(value)) return;
    _active = value;
    _apply(_resolve());
    _syncUI();
    fetch('/api/config', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme: value }),
    }).catch(() => {});
  }

  function getActive()    { return _active; }
  function getEffective() { return _resolve(); }

  return { init, set, getActive, getEffective, _syncUI };
})();
