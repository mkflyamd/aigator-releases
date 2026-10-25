// gator:pick-demo-folder replies to the widget with the native picker result.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function caseBlock() {
  const start = source.indexOf("case 'gator:pick-demo-folder': {");
  assert(start > 0, 'bridge case found');
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error('case block not closed');
}

const code = `(function (d, e, window) { switch (d.type) { ${caseBlock()} } })`;
const run = vm.runInNewContext(code, {});

async function main() {
  const sent = [];
  const e = { source: { postMessage: (m) => sent.push(m) } };
  run({ type: 'gator:pick-demo-folder' }, e, {
    gatorShell: { pickDemoFolder: async () => ({ ok: true, path: 'C:/demos' }) },
  });
  await new Promise((r) => setTimeout(r, 0));
  assert.deepStrictEqual(JSON.parse(JSON.stringify(sent[0])), {
    type: 'gator:pick-demo-folder-result',
    data: { ok: true, path: 'C:/demos' },
  });

  const sent2 = [];
  run({ type: 'gator:pick-demo-folder' }, { source: { postMessage: (m) => sent2.push(m) } }, {});
  await new Promise((r) => setTimeout(r, 0));
  assert.strictEqual(sent2[0].data.ok, false);
  console.log('demo_project_bridge: ok');
}
main();
