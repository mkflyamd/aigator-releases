// Preloaded into Node (NODE_OPTIONS --require) inside the Windows AppContainer.
'use strict';
const fs = require('fs');
const cp = require('child_process');
const { EventEmitter } = require('events');
const { PassThrough, Writable } = require('stream');

// The JS realpath lstat()s every path component including the drive root, which an AppContainer
// cannot read. The native realpath does not.
// If even the native call is denied, fall back to the absolute path (symlinks are already preserved).
const path = require('path');
const syncNative = fs.realpathSync.native;
const asyncNative = fs.realpath.native;
const denied = (e) => e && (e.code === 'EPERM' || e.code === 'EACCES');
fs.realpathSync = Object.assign(
  (p, ...rest) => {
    try {
      return syncNative(p, ...rest);
    } catch (e) {
      if (denied(e)) return path.resolve(String(p));
      throw e;
    }
  },
  { native: syncNative },
);
fs.realpath = Object.assign(
  (p, ...rest) => {
    const cb = rest.pop();
    asyncNative(p, ...rest, (e, r) => (denied(e) ? cb(null, path.resolve(String(p))) : cb(e, r)));
  },
  { native: asyncNative },
);

// libuv creates \\.\pipe\uv\... pipes for a child's piped stdio. An AppContainer is denied that
// namespace and libuv retries forever, hanging the whole event loop. Fail fast instead.
function blockedError() {
  const e = new Error(
    'spawn blocked: the AI Gator sandbox cannot create piped stdio for child processes ' +
      "(use stdio: 'ignore' or 'inherit')",
  );
  e.code = 'EPERM';
  return e;
}

function usesPipe(stdio) {
  if (stdio === undefined || stdio === null || stdio === 'pipe') return true;
  if (typeof stdio === 'string') return false;
  return Array.from({ length: 3 }, (_, i) => stdio[i]).some(
    (s) => s === undefined || s === null || s === 'pipe' || s === 'overlapped',
  );
}

function failedChild(err, callback) {
  const child = new EventEmitter();
  child.pid = undefined;
  child.stdin = new Writable({ write: (_chunk, _enc, done) => done() });
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.kill = () => false;
  process.nextTick(() => {
    child.stdout.end();
    child.stderr.end();
    if (callback) {
      callback(err, '', '');
      return;
    }
    child.emit('error', err);
    child.emit('close', -1, null);
  });
  return child;
}

function lastFunction(args) {
  const last = args[args.length - 1];
  return typeof last === 'function' ? last : undefined;
}

function optionsOf(args) {
  return args.slice(1).find((x) => x && typeof x === 'object' && !Array.isArray(x));
}

const originals = {};
for (const name of ['spawn', 'spawnSync', 'exec', 'execFile', 'execSync', 'execFileSync', 'fork'])
  originals[name] = cp[name];

cp.spawn = function (...a) {
  const opts = optionsOf(a);
  return usesPipe(opts && opts.stdio)
    ? failedChild(blockedError())
    : originals.spawn.apply(this, a);
};
cp.exec = function (...a) {
  return failedChild(blockedError(), lastFunction(a));
};
cp.execFile = function (...a) {
  return failedChild(blockedError(), lastFunction(a));
};
cp.fork = function (...a) {
  return failedChild(blockedError());
};
cp.spawnSync = function (...a) {
  const opts = optionsOf(a);
  if (usesPipe(opts && opts.stdio))
    return {
      error: blockedError(),
      status: null,
      signal: null,
      output: null,
      pid: 0,
      stdout: null,
      stderr: null,
    };
  return originals.spawnSync.apply(this, a);
};
cp.execSync = function (...a) {
  const opts = optionsOf(a);
  if (usesPipe(opts && opts.stdio)) throw blockedError();
  return originals.execSync.apply(this, a);
};
cp.execFileSync = function (...a) {
  const opts = optionsOf(a);
  if (usesPipe(opts && opts.stdio)) throw blockedError();
  return originals.execFileSync.apply(this, a);
};
