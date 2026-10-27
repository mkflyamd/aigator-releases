// A SharePoint/OneDrive webUrl keeps "(" and ")" from the file name literal. The chat
// link renderer must keep them inside the href instead of ending the link at the first ")".

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function extract(name) {
  const match = source.match(
    new RegExp('\\nfunction ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'),
  );
  assert(match, name + ' not found in app.js');
  return match[0];
}

const code =
  ['escapeHtml', 'applyInline', 'renderMarkdown'].map(extract).join('\n') + '\nrenderMarkdown;';
const renderMarkdown = vm.runInNewContext(code, {
  window: { location: { origin: 'http://127.0.0.1:8000' } },
});

const url =
  'https://amd-my.sharepoint.com/personal/x/Documents/Gator%20Meeting%20Transcripts/2026-W43/' +
  '2026-10-19%20AMD%20(Cohere)%20%5B4cfc8f71%5D.vtt';
const html = renderMarkdown(`[🔗 Open in OneDrive](${url})`);

assert(html.includes(`<a href="${url}"`), 'href must keep the parentheses: ' + html);
assert(
  html.includes('>🔗 Open in OneDrive</a>'),
  'link text must close the anchor, not leak the URL tail: ' + html,
);
assert(!/<\/a>[^<]*%5B4cfc8f71%5D/.test(html), 'URL tail leaked outside the anchor: ' + html);

const plain = renderMarkdown('[a](https://example.com/x) and [b](https://example.com/y)');
assert.strictEqual((plain.match(/<a /g) || []).length, 2, 'adjacent links must stay separate');

const wrapped = renderMarkdown('(see [a](https://example.com/x))');
assert(wrapped.includes('<a href="https://example.com/x"'), 'outer paren must not join the URL');

console.log('chat_link_parens: ok');
