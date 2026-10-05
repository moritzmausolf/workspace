#!/bin/bash
# Email -> Telegram forwarder, one-shot macOS installer.
# Double-click this file in Finder. Terminal opens and walks you through it.

set -u

APP_DIR="$HOME/EmailForwarder"
PLIST_LABEL="com.moritz.emailforwarder"
PLIST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
die()  { printf '\n\033[31mFailed: %s\033[0m\n\n' "$*"; printf 'Press return to close.'; read -r _; exit 1; }

clear
cat <<'BANNER'
==========================================
  Email  ->  Telegram  forwarder
==========================================
BANNER

# ---------------------------------------------------------------- python
say "1/5  Checking Python"
PY=""
for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [ -x "$candidate" ] && { PY="$candidate"; break; }
done
[ -n "$PY" ] || die "Python 3 not found. Install it from python.org, then run this again."
info "using $PY ($("$PY" -V 2>&1))"

# ---------------------------------------------------------------- files
say "2/5  Installing to $APP_DIR"
mkdir -p "$APP_DIR" || die "could not create $APP_DIR"
cd "$APP_DIR" || die "could not enter $APP_DIR"

cat > "$APP_DIR/email_to_telegram.py" <<'FORWARDER_EOF'
__FORWARDER_PY__
FORWARDER_EOF

cat > "$APP_DIR/setup_helper.py" <<'HELPER_EOF'
__HELPER_PY__
HELPER_EOF

if [ ! -f "$APP_DIR/config.json" ]; then
  cat > "$APP_DIR/config.json" <<'CONFIG_EOF'
__CONFIG_JSON__
CONFIG_EOF
  info "config.json written"
else
  info "config.json already exists - keeping it"
fi
info "forwarder installed"

# ---------------------------------------------------------------- deps
say "3/5  Installing Telethon (first run only, ~20s)"
if [ ! -x "$APP_DIR/.venv/bin/python3" ]; then
  "$PY" -m venv "$APP_DIR/.venv" || die "could not create the Python environment"
fi
VENV_PY="$APP_DIR/.venv/bin/python3"
"$VENV_PY" -m pip install --quiet --upgrade pip setuptools wheel >/dev/null 2>&1
"$VENV_PY" -m pip install --quiet telethon || die "could not install Telethon (check your internet connection)"
info "ready"

# ---------------------------------------------------------------- telegram
say "4/5  Telegram"
"$VENV_PY" "$APP_DIR/setup_helper.py" || die "Telegram setup did not finish"

# ---------------------------------------------------------------- service
say "5/5  Starting it in the background"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PLIST_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV_PY</string>
    <string>$APP_DIR/email_to_telegram.py</string>
  </array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$APP_DIR/forwarder.log</string>
  <key>StandardErrorPath</key><string>$APP_DIR/forwarder.log</string>
</dict>
</plist>
PLIST_EOF

launchctl bootout "gui/$(id -u)/$PLIST_LABEL" >/dev/null 2>&1 || launchctl unload "$PLIST" >/dev/null 2>&1
launchctl bootstrap "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || launchctl load "$PLIST" >/dev/null 2>&1
sleep 4

PORT="$("$VENV_PY" -c "import json;print(json.load(open('$APP_DIR/config.json')).get('dashboard_port',9876))" 2>/dev/null || echo 9876)"

if curl -fsS --max-time 5 "http://localhost:$PORT" >/dev/null 2>&1; then
  info "running"
else
  info "starting up - if the page does not load, check $APP_DIR/forwarder.log"
fi

open "http://localhost:$PORT" >/dev/null 2>&1 || true

cat <<DONE

==========================================
  Done.
==========================================

  On/off switch:  http://localhost:$PORT
                  (bookmark it in Arc)

  Log file:       $APP_DIR/forwarder.log

  It starts automatically when you log in.

DONE
printf 'Press return to close this window.'
read -r _
