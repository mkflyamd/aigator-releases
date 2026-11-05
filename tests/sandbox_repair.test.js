// The Electron shell removes stray sandbox access entries above its own folder before opening a window.

const assert = require('assert');
const path = require('path');
const test = require('node:test');
const { profileSid, sandboxSids, ancestors, hasDirectAce, repairSandboxGrants } = require('../shell/sandbox-repair');

const SHELL_SID = 'S-1-15-2-3490896091-3407169838-1873203060-1767053973-3959536481-805227709-1881130585';

test('the shell profile SID matches the one Windows gave the sandbox profile', () => {
  assert.strictEqual(profileSid('AIGator.CodeRunner.Shell'), SHELL_SID);
  assert.strictEqual(sandboxSids().length, 2);
  assert(sandboxSids().includes(SHELL_SID));
});

test('ancestors run from the folder to the drive root', () => {
  const dirs = ancestors('C:\\a\\b\\c');
  assert.deepStrictEqual(dirs.map((d) => d.toLowerCase()), ['c:\\a\\b\\c', 'c:\\a\\b', 'c:\\a', 'c:\\']);
});

test('only a direct entry counts, not an inherited one', () => {
  assert(hasDirectAce(`C:\\x ${SHELL_SID}:(OI)(CI)(RX)\r\n`, SHELL_SID));
  assert(!hasDirectAce(`C:\\x ${SHELL_SID}:(I)(OI)(CI)(RX)\r\n`, SHELL_SID));
  assert(!hasDirectAce('C:\\x BUILTIN\\Users:(OI)(CI)(RX)\r\n', SHELL_SID));
});

function fakeIcacls(acl) {
  const calls = [];
  const run = (_file, args) => {
    calls.push(args);
    const dir = args[0].toLowerCase();
    if (args[1] === '/remove:g') {
      assert.strictEqual(args[2], `*${SHELL_SID}`);
      delete acl[dir];
      return '';
    }
    return acl[dir] ? `${args[0]} ${SHELL_SID}:(OI)(CI)(RX)\r\n    BUILTIN\\Users:(RX)\r\n` : `${args[0]} BUILTIN\\Users:(RX)\r\n`;
  };
  return { run, calls };
}

test('removes the entry from the folder that has it and leaves the others alone', () => {
  const acl = { 'c:\\repo': true };
  const { run, calls } = fakeIcacls(acl);
  const removed = repairSandboxGrants({ startDir: 'C:\\repo\\node_modules\\electron\\dist', run });
  assert.deepStrictEqual(removed.map((r) => [r.dir.toLowerCase(), r.sid]), [['c:\\repo', SHELL_SID]]);
  assert.deepStrictEqual(calls.filter((a) => a[1] === '/remove:g').map((a) => a[0].toLowerCase()), ['c:\\repo']);
  assert.deepStrictEqual(acl, {});
});

test('does nothing when no folder has an entry', () => {
  const { run, calls } = fakeIcacls({});
  assert.deepStrictEqual(repairSandboxGrants({ startDir: 'C:\\repo\\shell', run }), []);
  assert(calls.every((a) => a.length === 1));
});

test('a folder icacls cannot read or change does not stop the repair', () => {
  const run = (_file, args) => {
    if (args[0].toLowerCase() === 'c:\\repo\\shell') throw new Error('access denied');
    if (args[1] === '/remove:g') throw new Error('access denied');
    return `${args[0]} ${SHELL_SID}:(RX)\r\n`;
  };
  assert.deepStrictEqual(repairSandboxGrants({ startDir: 'C:\\repo\\shell', run }), []);
});

test('main.js starts the repair before any window and the packaged build ships the module', () => {
  const fs = require('fs');
  const main = fs.readFileSync(path.join(__dirname, '..', 'shell', 'main.js'), 'utf8');
  assert(main.indexOf("require('./sandbox-repair')") !== -1);
  assert(main.indexOf("require('./sandbox-repair')") < main.indexOf('new BrowserWindow'));
  assert(main.includes('AIGATOR_APP_DIR: path.dirname(process.execPath)'));
  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'shell', 'package.json'), 'utf8'));
  assert(pkg.build.files.includes('sandbox-repair.js'));
});
