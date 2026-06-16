// Issue #65: a PDF attachment must render with a real PDF icon and a PDF type
// label — never a broken image and never misclassified as a Word/docx file.
// We extract the file-card helpers from app.js and verify PDF handling, and we
// assert the pdf-file.png asset actually exists on disk.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const STATIC = path.join(__dirname, '..', 'web', 'static');
const source = fs.readFileSync(path.join(STATIC, 'app.js'), 'utf8');

function grab(name) {
  const re = new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}');
  const m = source.match(re);
  assert(m, name + ' not found in app.js');
  return m[0];
}

// _fileIconImg / _friendlyMimeLabel both call _fileExt, so load all three into
// one shared context.
const ctx = {};
vm.runInNewContext(
  [grab('_fileExt'), grab('_fileIconImg'), grab('_friendlyMimeLabel')].join('\n'),
  ctx,
);
const { _fileIconImg, _friendlyMimeLabel } = ctx;

// ── PDF resolves to the PDF icon, by extension and by MIME ──
assert.strictEqual(_fileIconImg('application/pdf', 'AI_Gator_Production_Review.pdf'), '/static/icons/pdf-file.png');
assert.strictEqual(_fileIconImg('', 'report.pdf'), '/static/icons/pdf-file.png'); // extension wins when MIME is missing
assert.strictEqual(_fileIconImg('application/pdf', ''), '/static/icons/pdf-file.png'); // MIME fallback

// ── PDF must NEVER be classified as a Word document ──
assert.notStrictEqual(_fileIconImg('application/pdf', 'report.pdf'), '/static/icons/word-file.png');
assert.strictEqual(_friendlyMimeLabel('application/pdf', 'report.pdf'), 'PDF');
assert.notStrictEqual(_friendlyMimeLabel('application/pdf', 'report.pdf'), 'Word document');

// ── The PDF icon asset must exist so the <img> never renders broken ──
assert.ok(fs.existsSync(path.join(STATIC, 'icons', 'pdf-file.png')), 'pdf-file.png asset is missing');

// ── PDF must be excluded from every doc skill map (so it never triggers the
// docx/excel/ppt skill chip). Guards against a regression that adds pdf back. ──
const skillMaps = source.match(/skillMap\s*=\s*\{[^}]*\}/g) || [];
assert.ok(skillMaps.length > 0, 'no skillMap literals found in app.js');
for (const sm of skillMaps) {
  assert.ok(!/\bpdf\s*:/.test(sm), 'a skillMap maps pdf to a doc skill: ' + sm);
}

console.log('pdf_attachment: all assertions passed');
