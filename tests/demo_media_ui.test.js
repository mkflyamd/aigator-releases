const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'web', 'static', 'demo-media.js'), 'utf8');
const DemoMedia = vm.runInNewContext(source + '; DemoMedia;', { window: {}, document: {} });

// Objects built inside the vm have a different realm's prototypes; compare as plain JSON.
const plain = (value) => JSON.parse(JSON.stringify(value));

// classify
assert.strictEqual(DemoMedia.classify('Demo.MP4'), 'video');
assert.strictEqual(DemoMedia.classify('clip.webm'), 'video');
assert.strictEqual(DemoMedia.classify('bed.wav'), 'audio');
assert.strictEqual(DemoMedia.classify('report.docx'), null);
assert.strictEqual(DemoMedia.classify('noextension'), null);

// validateLocal
assert.strictEqual(DemoMedia.validateLocal({ name: 'a.mp4', size: 10 }), null);
assert.match(DemoMedia.validateLocal({ name: 'a.mp4', size: 0 }), /empty/i);
assert.match(DemoMedia.validateLocal({ name: 'a.mp4', size: 2 * 1024 ** 3 + 1 }), /2 GB/);

// formatDuration
assert.strictEqual(DemoMedia.formatDuration(0), '0:00');
assert.strictEqual(DemoMedia.formatDuration(65), '1:05');
assert.strictEqual(DemoMedia.formatDuration(599.6), '10:00');
assert.strictEqual(DemoMedia.formatDuration(3725), '62:05');

// parseTrim
assert.deepStrictEqual(plain(DemoMedia.parseTrim('', '', 10)), { ok: true, trim_start: 0, trim_end: null });
assert.deepStrictEqual(plain(DemoMedia.parseTrim('1', '6.5', 10)), { ok: true, trim_start: 1, trim_end: 6.5 });
assert.deepStrictEqual(plain(DemoMedia.parseTrim('2', '', 10)), { ok: true, trim_start: 2, trim_end: null });
for (const [s, e] of [['x', ''], ['-1', ''], ['0', 'abc'], ['0', '11'], ['2', '2.2'], ['9.8', '']]) {
  const r = DemoMedia.parseTrim(s, e, 10);
  assert.strictEqual(r.ok, false, `parseTrim(${s}, ${e}) should be rejected`);
  assert.ok(typeof r.error === 'string' && r.error.length > 0);
}

// moveId
assert.deepStrictEqual(plain(DemoMedia.moveId(['c1', 'c2', 'c3'], 'c2', -1)), ['c2', 'c1', 'c3']);
assert.deepStrictEqual(plain(DemoMedia.moveId(['c1', 'c2', 'c3'], 'c2', 1)), ['c1', 'c3', 'c2']);
assert.deepStrictEqual(plain(DemoMedia.moveId(['c1', 'c2'], 'c1', -1)), ['c1', 'c2']);
assert.deepStrictEqual(plain(DemoMedia.moveId(['c1', 'c2'], 'c2', 1)), ['c1', 'c2']);
assert.deepStrictEqual(plain(DemoMedia.moveId(['c1', 'c2'], 'zz', 1)), ['c1', 'c2']);

// wiring
const read = (...p) => fs.readFileSync(path.join(root, ...p), 'utf8');
const appJs = read('web', 'static', 'app.js');
const indexHtml = read('web', 'static', 'index.html');
const styleCss = read('web', 'static', 'style.css');
assert.ok(appJs.includes('DemoMedia.classify(file.name)'), 'processFiles routes media files');
assert.ok(appJs.includes('function _attachDemoMedia('), 'media chip helper exists');
assert.ok(appJs.includes('data-media-uploading'), 'submit gate checks uploading chips');
assert.ok(appJs.includes('Wait for the upload to finish'), 'submit gate message');
assert.ok(appJs.includes('DemoMedia.mountPanel('), 'panel is mounted');
assert.ok(indexHtml.includes('id="demo-media-panel"'), 'panel container');
assert.ok(indexHtml.includes('/static/demo-media.js'), 'script tag');
assert.ok(indexHtml.includes('.mp4,.mov,.m4v,.webm,.mp3,.m4a,.wav,.aac,.ogg,.flac'), 'file input accepts media');
assert.ok(styleCss.includes('.demo-media-panel'), 'panel styles');
assert.ok(
  indexHtml.indexOf('/static/demo-media.js') < indexHtml.indexOf('/static/app.js'),
  'demo-media.js loads before app.js',
);

console.log('demo_media_ui: ok');
