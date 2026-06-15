#!/usr/bin/env bash
# +==========================================================================+
# |  WakeGator - AI Gator one-command setup for macOS alpha testers           |
# |  Installs dependencies and wakes the gator (Tier 1: run-from-source).     |
# |  Usage:  bash WakeGator.sh            (full setup + launch)               |
# |     or:  bash WakeGator.sh --launch-only   (skip pip, just start)         |
# +==========================================================================+
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

LAUNCH_ONLY=0
[ "${1:-}" = "--launch-only" ] && LAUNCH_ONLY=1

LOG_DIR="$HOME/Library/Logs/AIGator"
LOG_FILE="$LOG_DIR/aigator.log"
mkdir -p "$LOG_DIR"

step() { printf '\n  %s\n' "$1"; }
ok()   { printf '      OK %s\n' "$1"; }
info() { printf '      -> %s\n' "$1"; }
warn() { printf '      ! %s\n' "$1"; }
err()  { printf '      x %s\n' "$1" >&2; }

VENV_DIR="$PROJECT_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"

# -- Resolve Python (inherited from Get-AIGator.sh, else discover) ------------
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

# -- Banner --------------------------------------------------------------------
VERSION=""
[ -f "$PROJECT_DIR/version.txt" ] && VERSION="$(tr -d '\r\n' < "$PROJECT_DIR/version.txt")"
printf '\n'
printf '                A I   G A T O R\n'
[ -n "$VERSION" ] && printf '                  v%s  -  Waking up...\n' "$VERSION"
printf '\n'

setup_env() {
    # -- Step 1: Python --------------------------------------------------------
    step "[1/4] Checking for Python 3.12"
    PY="${AIGATOR_PYTHON:-$(find_python || true)}"
    if [ -z "${PY}" ]; then
        err "Python 3.12+ is required. Install via 'brew install python@3.12'"
        err "or https://www.python.org/downloads/macos/, then run WakeGator again."
        exit 1
    fi
    ok "Found $("$PY" --version 2>&1)"

    # -- Step 2: Virtual environment ------------------------------------------
    step "[2/4] Setting up an isolated environment"
    if [ -x "$VENV_PY" ]; then
        ok "Environment already exists - reusing it."
    else
        info "Creating .venv ..."
        "$PY" -m venv "$VENV_DIR"
        if [ ! -x "$VENV_PY" ]; then
            err "Failed to create virtual environment."
            exit 1
        fi
        ok "Environment created."
    fi

    # -- Step 3: Dependencies --------------------------------------------------
    step "[3/4] Installing dependencies (a few minutes the first time)"
    if ! "$VENV_PY" -m pip install --upgrade pip --quiet; then
        warn "pip upgrade hit a snag - continuing anyway."
    fi
    if ! "$VENV_PY" -m pip install -r "$PROJECT_DIR/requirements.txt" --quiet; then
        err "Dependency install failed. If you're on a corporate network, a proxy may be blocking pip."
        exit 1
    fi
    ok "Dependencies installed."
}

write_start_command() {
    # A double-clickable relauncher that skips pip and just starts the server.
    local sc="$PROJECT_DIR/start.command"
    cat > "$sc" <<EOF
#!/usr/bin/env bash
cd "\$(dirname "\${BASH_SOURCE[0]}")"
exec bash WakeGator.sh --launch-only
EOF
    chmod +x "$sc"
}

launch() {
    # -- Step 4: Wake the gator -----------------------------------------------
    step "[4/4] Waking the gator"
    if [ ! -x "$VENV_PY" ]; then
        err "No environment found. Run 'bash WakeGator.sh' (without --launch-only) first."
        exit 1
    fi
    info "Starting the server in the background ..."
    nohup "$VENV_PY" web/watchdog.py >> "$LOG_FILE" 2>&1 &

    # Poll /health up to ~60s.
    local i=0
    local up=0
    printf '      '
    while [ $i -lt 60 ]; do
        if curl -fs http://localhost:8000/health >/dev/null 2>&1; then
            up=1
            break
        fi
        printf '.'
        sleep 1
        i=$((i + 1))
    done
    printf '\n'
    if [ $up -eq 1 ]; then
        ok "The gator is awake!  Chomp chomp."
    else
        warn "Server didn't answer within 60s - opening anyway."
        warn "Logs: $LOG_FILE"
    fi
    open http://localhost:8000 || true
}

if [ $LAUNCH_ONLY -eq 0 ]; then
    setup_env
    write_start_command
fi
launch

printf '\n'
info "To open it again later: double-click start.command in:"
info "$PROJECT_DIR"
printf '\n'
