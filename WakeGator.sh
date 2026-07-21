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

# Run a command in the background while showing a spinner + elapsed time.
# Usage: run_with_spinner "Label" cmd [args...]
run_with_spinner() {
    local label="$1"; shift
    local spin=('|' '/' '-' '\\')
    local i=0 start elapsed
    start=$(date +%s)
    "$@" >/dev/null 2>&1 &
    local pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        elapsed=$(( $(date +%s) - start ))
        printf '\r      %s %s  [%ds]' "${spin[$((i % 4))]}" "$label" "$elapsed"
        i=$((i + 1))
        sleep 0.15
    done
    wait "$pid"
    local code=$?
    printf '\r%78s\r' ''   # clear the spinner line
    return $code
}

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
    step "[1/5] Checking for Python 3.12"
    PY="${AIGATOR_PYTHON:-$(find_python || true)}"
    if [ -z "${PY}" ]; then
        err "Python 3.12+ is required. Install via 'brew install python@3.12'"
        err "or https://www.python.org/downloads/macos/, then run WakeGator again."
        exit 1
    fi
    ok "Found $("$PY" --version 2>&1)"

    # -- Step 2: Virtual environment ------------------------------------------
    step "[2/5] Setting up an isolated environment"
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
    step "[3/5] Installing dependencies (a few minutes the first time)"
    if ! run_with_spinner "Upgrading pip" "$VENV_PY" -m pip install --upgrade pip --quiet; then
        warn "pip upgrade hit a snag - continuing anyway."
    fi
    if ! run_with_spinner "Installing packages (first run downloads a lot — hang tight)" \
            "$VENV_PY" -m pip install -r "$PROJECT_DIR/requirements.txt" --quiet; then
        err "Dependency install failed. If you're on a corporate network, a proxy may be blocking pip."
        exit 1
    fi
    ok "Dependencies installed."

    # -- Step 4: Node.js runtime ----------------------------------------------
    # AI Gator ships its own portable Node in the app folder and prefers it at
    # runtime over any system Node (web/proc_utils.py:ensure_bundled_node_on_path),
    # so npx/node MCP servers work regardless of the user's Node install/PATH.
    # Non-fatal: if the download fails, the app still starts (just no npx/node MCP).
    step "[4/5] Setting up Node.js runtime (for npx/node MCP servers)"
    local node_version="22.14.0"
    local node_dir="$PROJECT_DIR/node"
    if [ -x "$node_dir/bin/node" ]; then
        ok "Node.js runtime already present."
    else
        local arch
        case "$(uname -m)" in
            arm64|aarch64) arch="arm64" ;;
            *)             arch="x64" ;;
        esac
        local node_name="node-v$node_version-darwin-$arch"
        local node_url="https://nodejs.org/dist/v$node_version/$node_name.tar.gz"
        local tmp_tgz tmp_ex
        tmp_tgz="$(mktemp -t aigator-node.XXXXXX).tar.gz"
        tmp_ex="$(mktemp -d -t aigator-node-ex.XXXXXX)"
        if run_with_spinner "Downloading Node.js $node_version" curl -fsSL "$node_url" -o "$tmp_tgz" && \
           run_with_spinner "Extracting Node.js" tar -xzf "$tmp_tgz" -C "$tmp_ex"; then
            # Flatten the versioned top-level folder so bin/node lands at node/ root.
            mkdir -p "$node_dir"
            cp -R "$tmp_ex/$node_name"/. "$node_dir"/
            if [ -x "$node_dir/bin/node" ]; then
                ok "Node.js $node_version ready."
            else
                warn "Node.js setup didn't complete - npx/node MCP servers may not work."
            fi
        else
            warn "Could not download Node.js - npx/node MCP servers may not work."
        fi
        rm -f "$tmp_tgz"; rm -rf "$tmp_ex"
    fi

    # -- Bundle OpenCode (pinned version, into the portable Node above) -------
    # Mirrors WakeGator.ps1's OpenCode step exactly - see
    # docs/internal/OpenCodeIntegrationPlan.md §4 for the pinning rationale.
    # NOT empirically tested on macOS - no Mac was available to verify this
    # against a real install. Built from npm's documented --prefix behavior:
    # unlike Windows (where global bins land directly in the prefix dir as
    # .cmd shims), Unix links them into {prefix}/bin - which is also exactly
    # why the Node step above expects node itself at node/bin/node, not
    # node/node. Non-fatal: if this fails, the app still starts, just
    # without the OpenCode coding-agent panel.
    local opencode_version="1.18.1"
    local opencode_bin="$node_dir/bin/opencode"
    if [ -x "$opencode_bin" ] && [ "$("$opencode_bin" --version 2>/dev/null)" = "$opencode_version" ]; then
        ok "OpenCode $opencode_version already present."
    elif [ -x "$node_dir/bin/node" ]; then
        info "Installing OpenCode $opencode_version (coding agent)..."
        if "$node_dir/bin/npm" install -g "opencode-ai@$opencode_version" --prefix "$node_dir" >/dev/null 2>&1 && \
           [ -x "$opencode_bin" ]; then
            ok "OpenCode $opencode_version ready."
        else
            warn "OpenCode setup didn't complete - the coding-agent panel may not work."
        fi
    else
        warn "Skipping OpenCode setup - Node.js bundle is not present."
    fi
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
    # -- Step 5: Wake the gator -----------------------------------------------
    step "[5/5] Waking the gator"
    if [ ! -x "$VENV_PY" ]; then
        err "No environment found. Run 'bash WakeGator.sh' (without --launch-only) first."
        exit 1
    fi
    info "Starting the server in the background ..."
    nohup "$VENV_PY" web/watchdog.py >> "$LOG_FILE" 2>&1 &

    # As soon as the watchdog HTTP server is alive (~1s), open the animated
    # loading page — it gives the user visual feedback and redirects itself to
    # the app when ready. This appears DURING the wait, not after it.
    local w=0
    while [ $w -lt 20 ]; do
        if curl -fs http://localhost:8001/status >/dev/null 2>&1; then
            open http://localhost:8001/loading || true
            break
        fi
        sleep 0.3
        w=$((w + 1))
    done

    # Meanwhile, keep this terminal a live progress bar: spinner + elapsed
    # seconds polling /health (the full app, after prefetch) up to ~90s.
    local spin='|/-\\'
    local si=0
    local start elapsed up=0
    start=$(date +%s)
    while [ $(( $(date +%s) - start )) -lt 90 ]; do
        if curl -fs http://localhost:8000/health >/dev/null 2>&1; then
            up=1
            break
        fi
        elapsed=$(( $(date +%s) - start ))
        printf '\r      %s Loading AI Gator...  [%ds]' "${spin:si%4:1}" "$elapsed"
        si=$((si + 1))
        sleep 0.2
    done
    printf '\r%78s\r' ''
    if [ $up -eq 1 ]; then
        ok "The gator is awake!  Chomp chomp."
    else
        warn "AI Gator is taking longer than usual - check your browser and the tray."
        warn "Logs: $LOG_FILE"
    fi
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
