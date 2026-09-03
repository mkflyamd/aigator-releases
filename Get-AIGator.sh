#!/usr/bin/env bash
set -euo pipefail

REPO="mkflyamd/aigator-releases"
API_URL="https://api.github.com/repos/${REPO}/releases?per_page=20"
KEEP_DOWNLOAD=0
NO_LAUNCH=0
DRY_RUN=0
MOUNT_DIR=""
MOUNTED=0

for argument in "$@"; do
    case "$argument" in
        --keep-download) KEEP_DOWNLOAD=1 ;;
        --no-launch) NO_LAUNCH=1 ;;
        --dry-run) DRY_RUN=1 ;;
        *) printf '[%s] ERROR Unknown option: %s\n' "$(date +%H:%M:%S)" "$argument" >&2; exit 2 ;;
    esac
done

log() {
    printf '[%s] %-5s %s\n' "$(date +%H:%M:%S)" "$1" "$2"
}

fail() {
    log ERROR "$1" >&2
    exit 1
}

CURL_COMMAND="${AIGATOR_INSTALLER_CURL:-}"
if [ -z "$CURL_COMMAND" ]; then
    command -v curl >/dev/null 2>&1 || fail "curl is required to download AI Gator."
fi

download() {
    if [ -n "$CURL_COMMAND" ]; then
        python3 "$CURL_COMMAND" "$@"
    else
        curl "$@"
    fi
}

OS_NAME="$(uname -s)"
MACHINE="$(uname -m)"
case "$OS_NAME:$MACHINE" in
    Darwin:x86_64) PLATFORM="macos"; ARCH="x64" ;;
    Darwin:arm64) PLATFORM="macos"; ARCH="arm64" ;;
    Linux:x86_64|Linux:amd64) PLATFORM="linux"; ARCH="x64" ;;
    Darwin:*) fail "AI Gator releases do not support this macOS architecture: $MACHINE" ;;
    Linux:*) fail "AI Gator releases do not support this Linux architecture: $MACHINE" ;;
    *) fail "This installer supports macOS and Linux only. Detected: $OS_NAME" ;;
esac

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ai-gator-install.XXXXXX")"
cleanup() {
    if [ "$MOUNTED" -eq 1 ]; then
        if hdiutil detach "$MOUNT_DIR" >/dev/null 2>&1; then
            log INFO "Detached the temporary disk image"
        else
            log WARN "Could not detach the temporary disk image at $MOUNT_DIR"
        fi
    fi
    if [ "$KEEP_DOWNLOAD" -eq 1 ]; then
        log INFO "Keeping downloaded files in $TMP_DIR"
    else
        rm -rf "$TMP_DIR"
        if [ -e "$TMP_DIR" ]; then
            log WARN "Could not remove all temporary files from $TMP_DIR"
        else
            log INFO "Removed temporary download files"
        fi
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

RELEASE_JSON="$TMP_DIR/release.json"
log INFO "Requesting the latest published release from $API_URL"
download --fail --silent --show-error --location \
    --header 'Accept: application/vnd.github+json' \
    --header 'X-GitHub-Api-Version: 2022-11-28' \
    --header 'User-Agent: AI-Gator-Installer' \
    "$API_URL" --output "$RELEASE_JSON"

select_assets_python() {
    "$PYTHON_COMMAND" - "$RELEASE_JSON" "$PLATFORM" "$ARCH" <<'PY'
import json
import re
import sys

path, platform, arch = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    releases = json.load(handle)
release = next((item for item in releases if not item.get("draft")), None)
if release is None:
    raise SystemExit("GitHub did not return a published release")
patterns = {
    ("macos", "x64"): r"^AI-Gator-.+-macOS-x64\.dmg$",
    ("macos", "arm64"): r"^AI-Gator-.+-macOS-arm64\.dmg$",
    ("linux", "x64"): r"^AI-Gator-.+-Linux-(?:x64|x86_64|amd64)\.AppImage$",
}
assets = release.get("assets", [])
selected = [asset for asset in assets if re.match(patterns[(platform, arch)], asset.get("name", ""))]
checksums = [asset for asset in assets if asset.get("name") == "SHA256SUMS.txt"]
if len(selected) != 1:
    raise SystemExit(f"expected one {platform} {arch} package, found {len(selected)}")
digest = selected[0].get("digest", "")
if len(checksums) != 1 and not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
    raise SystemExit("release has neither SHA256SUMS.txt nor a valid asset digest")
print(release["tag_name"])
print(selected[0]["name"])
print(selected[0]["browser_download_url"])
print(selected[0]["size"])
print(checksums[0]["browser_download_url"] if len(checksums) == 1 else "")
print(digest.split(":", 1)[1] if digest else "")
PY
}

select_assets_osascript() {
    osascript -l JavaScript - "$RELEASE_JSON" "$PLATFORM" "$ARCH" <<'JXA'
ObjC.import('Foundation');
const args = $.NSProcessInfo.processInfo.arguments.js.slice(4);
const data = $.NSData.dataWithContentsOfFile(args[0]);
const releases = JSON.parse($.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding).js);
const release = releases.find(item => !item.draft);
if (!release) throw new Error('GitHub did not return a published release');
const patterns = {
  'macos:x64': /^AI-Gator-.+-macOS-x64\.dmg$/,
  'macos:arm64': /^AI-Gator-.+-macOS-arm64\.dmg$/
};
const selected = release.assets.filter(asset => patterns[args[1] + ':' + args[2]].test(asset.name));
const checksums = release.assets.filter(asset => asset.name === 'SHA256SUMS.txt');
if (selected.length !== 1) throw new Error(`expected one ${args[1]} ${args[2]} package, found ${selected.length}`);
const digest = selected[0].digest || '';
if (checksums.length !== 1 && !/^sha256:[0-9a-fA-F]{64}$/.test(digest)) {
  throw new Error('release has neither SHA256SUMS.txt nor a valid asset digest');
}
console.log(release.tag_name);
console.log(selected[0].name);
console.log(selected[0].browser_download_url);
console.log(selected[0].size);
console.log(checksums.length === 1 ? checksums[0].browser_download_url : '');
console.log(digest.replace(/^sha256:/, ''));
JXA
}

PYTHON_COMMAND=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_COMMAND="python3"
elif command -v python >/dev/null 2>&1 && python -c 'import sys; raise SystemExit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1; then
    PYTHON_COMMAND="python"
fi
if [ -n "$PYTHON_COMMAND" ]; then
    ASSET_DATA="$(select_assets_python)" || fail "The latest release does not contain the required package and checksums."
elif [ "$OS_NAME" = "Darwin" ] && command -v osascript >/dev/null 2>&1; then
    ASSET_DATA="$(select_assets_osascript)" || fail "The latest release does not contain the required package and checksums."
else
    fail "Python 3 is required on Linux to read GitHub release metadata."
fi

TAG="$(printf '%s\n' "$ASSET_DATA" | sed -n '1p')"
ASSET_NAME="$(printf '%s\n' "$ASSET_DATA" | sed -n '2p')"
ASSET_URL="$(printf '%s\n' "$ASSET_DATA" | sed -n '3p')"
ASSET_SIZE="$(printf '%s\n' "$ASSET_DATA" | sed -n '4p')"
CHECKSUM_URL="$(printf '%s\n' "$ASSET_DATA" | sed -n '5p')"
ASSET_DIGEST="$(printf '%s\n' "$ASSET_DATA" | sed -n '6p')"
[ -n "$ASSET_NAME" ] || fail "Release metadata did not identify an installable package."

PACKAGE_PATH="$TMP_DIR/$ASSET_NAME"
CHECKSUM_PATH="$TMP_DIR/SHA256SUMS.txt"
log INFO "Selected release $TAG for $PLATFORM $ARCH"
log INFO "Downloading $ASSET_NAME ($ASSET_SIZE bytes)"
download --fail --silent --show-error --location "$ASSET_URL" --output "$PACKAGE_PATH"
if [ -n "$CHECKSUM_URL" ]; then
    log INFO "Downloading SHA256SUMS.txt"
    download --fail --silent --show-error --location "$CHECKSUM_URL" --output "$CHECKSUM_PATH"
    EXPECTED_HASH="$(awk -v name="$ASSET_NAME" '$2 == name || $2 == "*" name { print $1 }' "$CHECKSUM_PATH")"
    [ "$(printf '%s\n' "$EXPECTED_HASH" | grep -c . || true)" -eq 1 ] || fail "SHA256SUMS.txt does not contain exactly one checksum for $ASSET_NAME."
else
    EXPECTED_HASH="$ASSET_DIGEST"
fi
if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL_HASH="$(sha256sum "$PACKAGE_PATH" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
    ACTUAL_HASH="$(shasum -a 256 "$PACKAGE_PATH" | awk '{print $1}')"
else
    fail "A SHA-256 tool is required to verify the download."
fi
log INFO "Expected SHA-256: $EXPECTED_HASH"
log INFO "Actual SHA-256:   $ACTUAL_HASH"
[ "$(printf '%s' "$EXPECTED_HASH" | tr '[:upper:]' '[:lower:]')" = "$(printf '%s' "$ACTUAL_HASH" | tr '[:upper:]' '[:lower:]')" ] || fail "Checksum verification failed. The package will not be installed."
log OK "Checksum verified"

if [ "$DRY_RUN" -eq 1 ]; then
    log OK "Dry run completed without installing or launching AI Gator"
    exit 0
fi

if [ "$PLATFORM" = "macos" ]; then
    MOUNT_DIR="$TMP_DIR/mount"
    mkdir -p "$MOUNT_DIR" "$HOME/Applications"
    log INFO "Mounting the macOS disk image read-only"
    hdiutil attach "$PACKAGE_PATH" -nobrowse -readonly -mountpoint "$MOUNT_DIR" >/dev/null
    MOUNTED=1
    APP_SOURCE=""
    for candidate in "$MOUNT_DIR"/*.app "$MOUNT_DIR"/*/*.app; do
        if [ -d "$candidate" ] && [ "$(basename "$candidate")" = "AI Gator.app" ]; then
            APP_SOURCE="$candidate"
            break
        fi
    done
    [ -n "$APP_SOURCE" ] || fail "The disk image does not contain AI Gator.app."
    APP_DEST="$HOME/Applications/AI Gator.app"
    APP_STAGE="$HOME/Applications/.AI Gator.installing.$$"
    APP_BACKUP="$HOME/Applications/.AI Gator.previous.$$"
    log INFO "Copying AI Gator.app to a temporary installation path"
    rm -rf "$APP_STAGE" "$APP_BACKUP"
    ditto "$APP_SOURCE" "$APP_STAGE"
    if [ -d "$APP_DEST" ]; then
        mv "$APP_DEST" "$APP_BACKUP"
    fi
    if mv "$APP_STAGE" "$APP_DEST"; then
        rm -rf "$APP_BACKUP"
    else
        [ ! -d "$APP_BACKUP" ] || mv "$APP_BACKUP" "$APP_DEST"
        fail "Could not replace the existing AI Gator application."
    fi
    hdiutil detach "$MOUNT_DIR" >/dev/null
    MOUNTED=0
    log OK "AI Gator installed to $APP_DEST"
    if [ "$NO_LAUNCH" -eq 0 ]; then
        log INFO "Opening AI Gator"
        open "$APP_DEST"
    else
        log INFO "Skipping launch because --no-launch was provided"
    fi
else
    INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/ai-gator"
    BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
    APP_DEST="$INSTALL_DIR/AI-Gator.AppImage"
    mkdir -p "$INSTALL_DIR" "$BIN_DIR"
    log INFO "Installing the AppImage to $APP_DEST"
    install -m 0755 "$PACKAGE_PATH" "$APP_DEST"
    ln -sfn "$APP_DEST" "$BIN_DIR/ai-gator"
    log OK "AI Gator installed; command: $BIN_DIR/ai-gator"
    if [ "$NO_LAUNCH" -eq 0 ]; then
        log INFO "Opening AI Gator"
        "$APP_DEST" >/dev/null 2>&1 &
        LAUNCH_PID=$!
        sleep 1
        if kill -0 "$LAUNCH_PID" 2>/dev/null; then
            log OK "AI Gator launch started"
        else
            fail "AI Gator exited immediately. Run $BIN_DIR/ai-gator in a terminal for details."
        fi
    else
        log INFO "Skipping launch because --no-launch was provided"
    fi
fi
