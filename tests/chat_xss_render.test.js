// M_05: the chat renderer must not turn model or tool output into live markup.
// We extract renderMarkdown and its helpers from app.js and run payloads through them.

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

function render(payload) {
  return renderMarkdown(payload);
}

// Tags and attributes that would run script when the HTML is inserted into the page.
const LIVE_TAG = /<\s*(script|iframe|object|embed|svg|img|style|link|meta|form)\b/i;
const LIVE_HANDLER = /<[^>]*\son[a-z]+\s*=/i;
const SCRIPT_URL =
  /<[^>]*\b(href|src|action|formaction)\s*=\s*["']?\s*(javascript|data|vbscript):/i;

const payloads = [
  '<script>alert(1)</script>',
  '<img src=x onerror=alert(1)>',
  '<svg onload=alert(1)>',
  '<iframe src="javascript:alert(1)"></iframe>',
  '<a href="javascript:alert(1)">click</a>',
  '[click](javascript:alert(1))',
  '[click](https://example.com" onmouseover="alert(1))',
  '[click](https://example.com)" onmouseover="alert(1)',
  '![x](https://example.com/a.png" onerror="alert(1))',
  '![x](javascript:alert(1))',
  '**<img src=x onerror=alert(1)>**',
  '`<script>alert(1)</script>`',
  '```\n<script>alert(1)</script>\n```',
  '| a | b |\n|---|---|\n| <img src=x onerror=alert(1)> | y |',
  '- <script>alert(1)</script>',
  '# <img src=x onerror=alert(1)>',
  '> <svg onload=alert(1)>',
  'https://example.com/"><script>alert(1)</script>',
  'https://example.com/?q=<img src=x onerror=alert(1)>',
  '<a href="https://example.com" onclick="alert(1)">x</a>',
  '<style>body{background:url(javascript:alert(1))}</style>',
  '<form action="https://evil.example"><input name=t></form>',
];

// Guard against a vacuous pass: the renderer must still produce normal markup and show hostile text as text.
const benign = render('ok **bold** [site](https://example.com)');
assert.match(benign, /<strong>bold<\/strong>/);
assert.match(benign, /<a href="https:\/\/example\.com"/);
assert.match(render('<img src=x onerror=alert(1)>'), /&lt;img src=x onerror=alert\(1\)&gt;/);

for (const payload of payloads) {
  const html = render(payload);
  assert.doesNotMatch(html, LIVE_TAG, 'live tag in output for: ' + payload + '\n' + html);
  assert.doesNotMatch(html, LIVE_HANDLER, 'event handler in output for: ' + payload + '\n' + html);
  assert.doesNotMatch(html, SCRIPT_URL, 'script URL in output for: ' + payload + '\n' + html);
}

console.log('chat_xss_render: all assertions passed');
