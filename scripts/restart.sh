#!/usr/bin/env bash
#
# Restart the ccbot daemon running in its own tmux session.
#
#   ./scripts/restart.sh              reinstall from this checkout, then restart
#   ./scripts/restart.sh --no-install restart the installed binary as-is
#
# The bot runs as `ccbot` (installed with `uv tool install`) inside the tmux
# session $CCBOT_DAEMON_SESSION (default: ccbot-daemon).  That session is
# separate from the "ccbot" session holding the Claude Code windows, which this
# script never touches — running sessions survive a restart.
set -euo pipefail

SESSION="${CCBOT_DAEMON_SESSION:-ccbot-daemon}"
WINDOW="ccbot"
# tmux resolves an exact session name first, so "ccbot-daemon" never hits the
# "ccbot" session. The "=" prefix works for -t session targets (has-session,
# kill-session) but not for the pane targets used by send-keys/pipe-pane.
PANE_TARGET="${SESSION}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="${CCBOT_LOG_FILE:-$HOME/.ccbot/run.log}"
MAX_WAIT=15  # seconds to wait for a graceful shutdown

INSTALL=1
for arg in "$@"; do
    case "$arg" in
        --no-install) INSTALL=0 ;;
        -h|--help) sed -n '3,9p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

is_running() {
    tmux has-session -t "=${SESSION}" 2>/dev/null
}

# 1. Install first: a broken build must not leave the bot stopped.
if [ "$INSTALL" -eq 1 ]; then
    echo "Installing ccbot from ${PROJECT_DIR}..."
    uv tool install --force "$PROJECT_DIR"
fi

CCBOT_BIN="$(command -v ccbot || true)"
if [ -z "$CCBOT_BIN" ]; then
    echo "Error: 'ccbot' not found in PATH (is ~/.local/bin on PATH?)" >&2
    exit 1
fi

# 2. Stop the old instance. Ctrl-C first so post_shutdown can flush queues and
#    stop the session monitor; kill-session only as a fallback.
if is_running; then
    echo "Stopping ${SESSION}..."
    tmux send-keys -t "$PANE_TARGET" C-c
    waited=0
    while is_running && [ "$waited" -lt "$MAX_WAIT" ]; do
        sleep 1
        waited=$((waited + 1))
    done
    if is_running; then
        echo "  Still up after ${MAX_WAIT}s, killing the session..."
        tmux kill-session -t "=${SESSION}"
        sleep 1
    fi
    echo "Stopped."
else
    echo "No ${SESSION} session running."
fi

# 3. Start it again and re-attach the log pipe (pipe-pane does not survive).
echo "Starting ${SESSION}..."
mkdir -p "$(dirname "$LOG_FILE")"
# Start in $HOME so a stray ./.env in some other cwd cannot override ~/.ccbot/.env
tmux new-session -d -s "$SESSION" -n "$WINDOW" -c "$HOME" "$CCBOT_BIN"
tmux pipe-pane -o -t "$PANE_TARGET" "cat >> '${LOG_FILE}'"

sleep 3
if ! is_running; then
    echo "Error: ${SESSION} exited immediately. Last output:" >&2
    tail -20 "$LOG_FILE" >&2 || true
    exit 1
fi

echo "ccbot restarted (logging to ${LOG_FILE}). Recent output:"
echo "----------------------------------------"
tmux capture-pane -t "$PANE_TARGET" -p | grep -v '^$' | tail -15
echo "----------------------------------------"
