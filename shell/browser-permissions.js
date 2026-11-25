'use strict';

// The Browser pane loads arbitrary sites, so its session grants nothing:
// every permission request and check is denied and screen capture is refused.
// Child windows (auth popups) share this session, so they inherit the policy.
function applyBrowserPermissions(ses) {
  ses.setPermissionRequestHandler((_webContents, _permission, callback) => {
    callback(false);
  });
  ses.setPermissionCheckHandler(() => false);
  if (typeof ses.setDisplayMediaRequestHandler === 'function') {
    ses.setDisplayMediaRequestHandler((_request, callback) => callback({}));
  }
}

module.exports = { applyBrowserPermissions };
