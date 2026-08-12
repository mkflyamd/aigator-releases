const { desktopCapturer } = require('electron');

// Shared origin-restricted mic/camera/screen-share policy for Slack + Teams.
//
// Applied per-session (not globally on session.defaultSession) so no
// untrusted origin ever inherits media access.
//
// Allowed origins (confirmed via spike; extend if new auth subdomains appear):
const MEDIA_ALLOWED_ORIGINS = [
  'https://app.slack.com',
  'https://teams.microsoft.com',
  'https://login.microsoftonline.com',
  'https://teams.live.com',
  'https://presence.teams.microsoft.com',
];

function _isAllowed(url) {
  if (!url) return false;
  try {
    const origin = new URL(url).origin;
    return MEDIA_ALLOWED_ORIGINS.some((o) => origin === o || origin.endsWith('.' + new URL(o).hostname));
  } catch {
    return false;
  }
}

// Permissions that must be granted for enterprise SSO/MFA to work inside the
// embedded pane. Generic across IdPs — not app- or tenant-specific:
//   - local-network-access: Okta FastPass / Duo / Ping talk to an on-device
//     helper over loopback. Chromium 130+ gates this; deny => "The browser is
//     blocking communication with Okta Verify" and sign-in fails.
//   - notifications: Teams requests on startup.
//   - clipboard-*, idle-detection: commonly requested by Teams/Slack, harmless.
const AUTH_FLOW_PERMISSIONS = new Set([
  'local-network-access',
  'notifications',
  'clipboard-read',
  'clipboard-sanitized-write',
  'idle-detection',
]);

// Wire mic/camera + screen-share + SSO permission handlers onto a session.
// Call once per session at creation time (persist:slack, persist:teams).
function applyMediaPermissions(ses) {
  ses.setPermissionRequestHandler((webContents, permission, callback, details) => {
    if (permission === 'media') {
      callback(_isAllowed(details && details.requestingUrl));
      return;
    }
    if (AUTH_FLOW_PERMISSIONS.has(permission)) { callback(true); return; }
    callback(false);
  });

  ses.setPermissionCheckHandler((webContents, permission, requestingOrigin) => {
    if (permission === 'media') return _isAllowed(requestingOrigin);
    if (AUTH_FLOW_PERMISSIONS.has(permission)) return true;
    return false;
  });

  // Screen sharing: wire to desktopCapturer with Electron's system picker.
  // useSystemPicker: true shows the OS-native source chooser — the user must
  // explicitly select a window or screen. Never auto-selects a source.
  if (typeof ses.setDisplayMediaRequestHandler === 'function') {
    ses.setDisplayMediaRequestHandler((_request, callback) => {
      desktopCapturer.getSources({ types: ['screen', 'window'] })
        .then((sources) => {
          // sources[0] is the system picker's selection when useSystemPicker
          // is true — the user has already chosen at OS level.
          callback({ video: sources[0] || null });
        })
        .catch(() => callback({}));
    }, { useSystemPicker: true });
  }
}

module.exports = { applyMediaPermissions };
