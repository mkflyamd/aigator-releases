// Removes sandbox access entries (ACEs) that a crashed or racing sandboxed run left on the folders above
// the Electron program. Electron's GPU and renderer processes die at launch (0x80000003) when any
// AppContainer ACE sits on or above its folder, so this runs before the first window is created.
//
// The two AppContainer SIDs are derived from the profile names in web/sandbox/launcher_windows.py
// (SHA-256 of the lowercase name in UTF-16LE, seven little-endian 32-bit words), so a lost or damaged
// grant ledger cannot hide the entries.

const crypto = require('crypto');
const path = require('path').win32;
const { execFileSync } = require('child_process');

const PROFILE_NAMES = ['AIGator.CodeRunner', 'AIGator.CodeRunner.Shell'];

function profileSid(name) {
  const digest = crypto.createHash('sha256').update(name.toLowerCase(), 'utf16le').digest();
  const words = [];
  for (let i = 0; i < 7; i += 1) words.push(digest.readUInt32LE(i * 4));
  return `S-1-15-2-${words.join('-')}`;
}

function sandboxSids() {
  return PROFILE_NAMES.map(profileSid);
}

function ancestors(startDir) {
  const dirs = [];
  let current = path.resolve(startDir);
  for (;;) {
    dirs.push(current);
    const parent = path.dirname(current);
    if (parent === current) return dirs;
    current = parent;
  }
}

function defaultRun(file, args) {
  return execFileSync(file, args, {
    encoding: 'utf8',
    windowsHide: true,
    timeout: 10000,
    stdio: ['ignore', 'pipe', 'ignore'],
  });
}

function icaclsExe() {
  return path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'icacls.exe');
}

// A direct (not inherited) entry for the SID on the folder itself.
function hasDirectAce(listing, sid) {
  const needle = sid.toUpperCase();
  return listing
    .split(/\r?\n/)
    .some((line) => line.toUpperCase().includes(needle) && !line.includes('(I)'));
}

function repairSandboxGrants({ startDir, run = defaultRun, sids = sandboxSids() }) {
  const removed = [];
  for (const dir of ancestors(startDir)) {
    let listing;
    try {
      listing = run(icaclsExe(), [dir]);
    } catch {
      continue;
    }
    for (const sid of sids) {
      if (!hasDirectAce(listing, sid)) continue;
      try {
        run(icaclsExe(), [dir, '/remove:g', `*${sid}`, '/Q']);
        removed.push({ dir, sid });
      } catch {
        // an unfixable folder must not stop the app from starting
      }
    }
  }
  return removed;
}

module.exports = { profileSid, sandboxSids, ancestors, hasDirectAce, repairSandboxGrants };
