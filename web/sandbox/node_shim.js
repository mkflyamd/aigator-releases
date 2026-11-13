// Preloaded into Node (NODE_OPTIONS --require) inside the Windows AppContainer.
'use strict';
const fs = require('fs');
const cp = require('child_process');
const { EventEmitter } = require('events');

// The JS realpath lstat()s every path component including the drive root, which an AppContainer
// cannot read. The native realpath does not.
const syncNative = fs.realpathSync.native;
const asyncNative = fs.realpath.native;
fs.realpathSync = Object.assign((...a) => syncNative(...a), { native: syncNative });
fs.realpath = Object.assign((...a) => asyncNative(...a), { native: asyncNative });

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
  child.stdin = child.stdout = child.stderr = null;
  child.kill = () => false;
  process.nextTick(() => {
    if (callback) callback(err, '', '');
    else child.emit('error', err);
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
