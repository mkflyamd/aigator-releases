#!/usr/bin/env bash
# +==========================================================================+
# |  Get-AIGator - one-line bootstrap for AI Gator on macOS (source track)    |
# |  Downloads the latest source, extracts it, and runs WakeGator.            |
# |                                                                           |
# |  Paste-and-go:                                                            |
# |    curl -fsSL https://raw.githubusercontent.com/mkflyamd/aigator-releases/main/Get-AIGator.sh | bash
# |                                                                           |
# |  Or download this file and run it:                                        |
# |    bash Get-AIGator.sh                                                    |
# +==========================================================================+
set -euo pipefail

REPO="mkflyamd/aigator-releases"
ZIP_URL="https://github.com/${REPO}/archive/refs/heads/main.zip"
DEST="$HOME/Applications/AIGator"

info() { printf '      -> %s\n' "$1"; }
ok()   { printf '      OK %s\n' "$1"; }
fail() { printf '      x %s\n' "$1" >&2; }

# Ask the user to approve an action before we run it. Reads from the controlling
# terminal so the prompt works even when this script is piped via `curl | bash`
# (where stdin is the script text, not the keyboard). Defaults to yes on Enter.
# Auto-approves when no terminal is attached (non-interactive/automated runs) so
# we don't hang a pipeline.
confirm() {  # confirm <question>
    local reply
    # Write the prompt to the terminal; if there is none, auto-approve quietly.
    { printf '      ? %s [Y/n] ' "$1" > /dev/tty; } 2>/dev/null || return 0
    read -r reply < /dev/tty 2>/dev/null || return 0
    case "$reply" in
        [nN] | [nN][oO]) return 1 ;;
        *)               return 0 ;;
    esac
}

printf '\n  AI Gator - fetching the latest version...\n\n'

# -- Resolve a real Python 3.12+ ----------------------------------------------
# Mirrors WakeGator.ps1's Get-Python312: prefer python3.12, fall back to any
# python3 that reports >= 3.12. If none, install via Homebrew when available,
# else print python.org instructions and exit.
find_python() {
    local cand
    for cand in python3.12 python3; do
        if command -v "$cand" >/dev/null 2>&1; then
            if "$cand" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)' >/dev/null 2>&1; then
                command -v "$cand"
                return 0
            fi
        fi
    done
    return 1
}

PY="$(find_python || true)"
if [ -z "${PY}" ]; then
    info "No Python 3.12+ found."
    if command -v brew >/dev/null 2>&1; then
        if confirm "Install Python 3.12 with Homebrew now? (a few minutes)"; then
            info "Installing Python 3.12 with Homebrew ..."
            brew install python@3.12
            # brew keg-only formula: the binary is python3.12 on PATH after linking.
            PY="$(find_python || true)"
        else
            info "Skipped Homebrew install."
        fi
    fi
fi
if [ -z "${PY}" ]; then
    fail "Python 3.12+ is required."
    fail "Install it from https://www.python.org/downloads/macos/ (or 'brew install python@3.12'),"
    fail "then run this installer again."
    exit 1
fi
ok "Using $("$PY" --version 2>&1)"

# -- Download + extract --------------------------------------------------------
TMP_ZIP="$(mktemp -t aigator.XXXXXX).zip"
TMP_EX="$(mktemp -d -t aigator-ex.XXXXXX)"
cleanup() { rm -f "$TMP_ZIP"; rm -rf "$TMP_EX"; }
trap cleanup EXIT

info "Downloading source ..."
if ! curl -fsSL "$ZIP_URL" -o "$TMP_ZIP"; then
    fail "Could not download AI Gator."
    fail "If you're on a corporate network, a proxy may be blocking the download."
    exit 1
fi
ok "Downloaded."

info "Extracting ..."
unzip -q "$TMP_ZIP" -d "$TMP_EX"
INNER="$(find "$TMP_EX" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
if [ -z "$INNER" ]; then
    fail "Unexpected archive layout - no top-level folder found."
    exit 1
fi

# Copy source into place, overwriting files but leaving an existing .venv intact
# so re-runs (updates) skip the slow full reinstall. Same semantics as the PS version.
mkdir -p "$DEST"
# cp -R of the inner contents; rsync would be cleaner but isn't guaranteed present.
cp -R "$INNER"/. "$DEST"/
ok "Installed to $DEST"

# -- Hand off to setup ---------------------------------------------------------
WAKE="$DEST/WakeGator.sh"
if [ ! -f "$WAKE" ]; then
    fail "Setup script not found at $WAKE"
    exit 1
fi
chmod +x "$WAKE"

printf '\n'
info "Handing off to setup ..."
printf '\n'
AIGATOR_PYTHON="$PY" exec bash "$WAKE"
