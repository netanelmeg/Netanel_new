#!/usr/bin/env bash
#
# install-bot.sh — set up and run the mdconvert Telegram bot on Linux / WSL.
#
# What it does (idempotent — safe to re-run):
#   1. Creates a Python virtualenv at python/.venv
#   2. Installs python-telegram-bot (+ optional PDF/Excel/Word/PowerPoint libs)
#   3. Asks for your bot token, validates it against Telegram's getMe API,
#      and saves it to ~/.config/mdconvert/bot.env (chmod 600)
#   4. Writes a launcher (~/.config/mdconvert/run-bot.sh)
#   5. If systemd is available (WSL2 with systemd enabled), installs and starts
#      a user service "mdconvert-bot" that auto-restarts and survives reboots;
#      otherwise prints manual / Task Scheduler instructions.
#
# Usage:
#   ./install-bot.sh                       # prompts for the token
#   ./install-bot.sh --token "123:ABC..."  # non-interactive
#   ./install-bot.sh --no-extras           # skip PDF/Excel/Word/PowerPoint libs
#   ./install-bot.sh --no-service          # don't install the systemd service
#   ./install-bot.sh --skip-validation     # don't call getMe (offline install)
#
set -euo pipefail

# --- locate the repo ------------------------------------------------------- #
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PY_DIR="$REPO_ROOT/python"
if [[ ! -d "$PY_DIR/mdconvert" ]]; then
    echo "error: mdconvert package not found at $PY_DIR/mdconvert" >&2
    exit 1
fi

# --- parse args ------------------------------------------------------------ #
TOKEN="${TELEGRAM_BOT_TOKEN:-}"
INSTALL_SERVICE="auto"   # auto | yes | no
SKIP_VALIDATION=0
SKIP_EXTRAS=0

usage() {
    cat <<'USAGE'
install-bot.sh — set up and run the mdconvert Telegram bot on Linux / WSL.

Usage:
  ./install-bot.sh                       # prompts for the token
  ./install-bot.sh --token "123:ABC..."  # non-interactive
  ./install-bot.sh --no-extras           # skip PDF/Excel/Word/PowerPoint libs
  ./install-bot.sh --no-service          # don't install the systemd service
  ./install-bot.sh --skip-validation     # don't call getMe (offline install)
  ./install-bot.sh --help                # show this help

The token can also come from the TELEGRAM_BOT_TOKEN environment variable.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --token)            TOKEN="${2:-}"; shift 2 ;;
        --token=*)          TOKEN="${1#*=}"; shift ;;
        --service)          INSTALL_SERVICE="yes"; shift ;;
        --no-service)       INSTALL_SERVICE="no"; shift ;;
        --skip-validation)  SKIP_VALIDATION=1; shift ;;
        --no-extras)        SKIP_EXTRAS=1; shift ;;
        -h|--help)          usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

# --- token ----------------------------------------------------------------- #
if [[ -z "$TOKEN" ]]; then
    read -rsp "Paste your bot token (from @BotFather): " TOKEN
    echo
fi
TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
if [[ -z "$TOKEN" ]]; then
    echo "error: no token provided." >&2
    exit 1
fi

# --- validate the token via getMe ----------------------------------------- #
if [[ "$SKIP_VALIDATION" -eq 0 ]]; then
    if command -v curl >/dev/null 2>&1; then
        echo "Validating token with Telegram getMe ..."
        RESP="$(curl -fsS "https://api.telegram.org/bot${TOKEN}/getMe" 2>/dev/null || true)"
        if printf '%s' "$RESP" | grep -q '"ok":true'; then
            UNAME="$(printf '%s' "$RESP" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')"
            echo "Token OK — bot @${UNAME:-unknown}"
        else
            echo "error: token validation failed. Response: ${RESP:-<none>}" >&2
            echo "Re-run with --skip-validation to bypass (e.g. offline install)." >&2
            exit 1
        fi
    else
        echo "note: curl not found; skipping token validation."
    fi
fi

# --- python + dependencies ------------------------------------------------- #
if ! command -v python3 >/dev/null 2>&1; then
    echo "error: python3 not found. Install it with: sudo apt update && sudo apt install -y python3 python3-venv" >&2
    exit 1
fi

VENV="$PY_DIR/.venv"
if [[ ! -d "$VENV" ]]; then
    echo "Creating virtualenv at $VENV ..."
    python3 -m venv "$VENV" || {
        echo "error: could not create venv. Try: sudo apt install -y python3-venv" >&2
        exit 1
    }
fi

PYBIN="$VENV/bin/python"
echo "Upgrading pip ..."
"$PYBIN" -m pip install --quiet --upgrade pip

echo "Installing python-telegram-bot ..."
"$PYBIN" -m pip install --quiet "python-telegram-bot>=20"

if [[ "$SKIP_EXTRAS" -eq 0 ]]; then
    echo "Installing optional format libraries (PDF / Excel / Word / PowerPoint) ..."
    if ! "$PYBIN" -m pip install --quiet -r "$PY_DIR/mdconvert/requirements.txt"; then
        echo "warning: some optional libraries failed to install — text/CSV/TSV/JSON/HTML still work." >&2
    fi
fi

# --- persist the token + launcher ----------------------------------------- #
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/mdconvert"
mkdir -p "$CFG_DIR"
ENV_FILE="$CFG_DIR/bot.env"
( umask 077; printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TOKEN" > "$ENV_FILE" )
chmod 600 "$ENV_FILE"
echo "Saved token to $ENV_FILE (readable only by you)."

LAUNCHER="$CFG_DIR/run-bot.sh"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Auto-generated by install-bot.sh — runs the mdconvert Telegram bot.
set -euo pipefail
set -a
source "$ENV_FILE"
set +a
cd "$PY_DIR"
exec "$PYBIN" -m mdconvert.bot
EOF
chmod +x "$LAUNCHER"
echo "Created launcher $LAUNCHER"

# --- systemd service (always-on) ------------------------------------------ #
have_systemd() {
    [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1
}

SERVICE_INSTALLED=0
if [[ "$INSTALL_SERVICE" != "no" ]]; then
    if have_systemd; then
        UNIT_DIR="$HOME/.config/systemd/user"
        mkdir -p "$UNIT_DIR"
        UNIT="$UNIT_DIR/mdconvert-bot.service"
        cat > "$UNIT" <<EOF
[Unit]
Description=mdconvert Telegram bot (file -> Markdown)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$PY_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$PYBIN -m mdconvert.bot
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
        echo "Wrote systemd user unit $UNIT"
        systemctl --user daemon-reload
        systemctl --user enable --now mdconvert-bot.service
        loginctl enable-linger "$USER" >/dev/null 2>&1 \
            || echo "note: could not enable linger; the bot may stop when you close WSL."
        SERVICE_INSTALLED=1
    elif [[ "$INSTALL_SERVICE" == "yes" ]]; then
        echo "warning: systemd is not available in this WSL distro; skipping service install." >&2
        echo "         Enable systemd: add '[boot]\\nsystemd=true' to /etc/wsl.conf, then 'wsl --shutdown'." >&2
    fi
fi

# --- final guidance -------------------------------------------------------- #
echo
echo "=========================================================================="
if [[ "$SERVICE_INSTALLED" -eq 1 ]]; then
    echo "✅ Bot installed and started as a systemd user service."
    echo
    echo "   Status:   systemctl --user status mdconvert-bot"
    echo "   Logs:     journalctl --user -u mdconvert-bot -f"
    echo "   Restart:  systemctl --user restart mdconvert-bot"
    echo "   Stop:     systemctl --user stop mdconvert-bot"
else
    echo "✅ Bot installed. systemd not used — start it manually:"
    echo
    echo "   Foreground:  $LAUNCHER"
    echo "   Background:  nohup $LAUNCHER > $CFG_DIR/bot.log 2>&1 &"
    echo
    echo "   Auto-start at Windows boot — create a Task Scheduler task that runs:"
    echo "     wsl.exe -- $LAUNCHER"
fi
echo
echo "Now open Telegram, message your bot, and send it a file as a *Document*."
echo
echo "⚠  This token now belongs to mdconvert. Stop any OTHER program polling the"
echo "   same bot (e.g. your Gemini agent) or Telegram returns a getUpdates Conflict."
echo "=========================================================================="
