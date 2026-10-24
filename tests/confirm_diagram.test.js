// The confirm card shows the schedule diagram when Mermaid renders it, and drops the box when it cannot.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const pick = (name) => {
  const m = source.match(new RegExp(String.raw`\n(async )?function ${name}\([^)]*\)\s*\{[\s\S]*?\n\}`));
  assert(m, `${name} not found in app.js`);
  return m[0];
};

function run(mermaid) {
  const box = { style: {}, innerHTML: '', removed: false, remove() { this.removed = true; } };
  const win = { mermaid };
  const ctx = { window: win, document: { createElement() { throw new Error('script must not load'); } } };
  vm.runInNewContext(`${pick('_loadMermaid')}\n${pick('_renderConfirmDiagram')}\nthis.go = _renderConfirmDiagram;`, ctx);
  return ctx.go(box, 'flowchart TD').then(() => ({ box, win }));
}

(async () => {
  const ok = await run({
    initialize() {},
    render: async (id, text) => ({ svg: `<svg data-id="${id}">${text}</svg>` }),
  });
  assert(ok.box.innerHTML.startsWith('<svg'), 'svg is shown');
  assert.strictEqual(ok.box.style.display, 'block', 'box is made visible');
  assert.strictEqual(ok.box.removed, false);

  const bad = await run({ initialize() {}, render: async () => { throw new Error('parse error'); } });
  assert.strictEqual(bad.box.removed, true, 'a diagram that fails to render is dropped, the text stays');

  const src = source.match(/function _loadMermaid[\s\S]*?\n\}/)[0];
  assert(src.includes("securityLevel: 'strict'"), 'Mermaid runs in strict mode');
  assert(src.includes('/static/vendor/mermaid/mermaid.min.js'), 'Mermaid is loaded from the bundled file');
  console.log('confirm_diagram: ok');
})();
