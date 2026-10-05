#!/bin/bash
# Email -> Telegram forwarder, one-shot macOS installer.
# Double-click this file in Finder. Terminal opens and walks you through it.

set -u

APP_DIR="$HOME/EmailForwarder"
LABEL="com.moritz.emailforwarder"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

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
say "1/4  Checking Python"
PY=""
for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [ -x "$candidate" ] && { PY="$candidate"; break; }
done
[ -n "$PY" ] || die "Python 3 not found. Install it from python.org, then run this again."
info "using $PY ($("$PY" -V 2>&1))"

# ---------------------------------------------------------------- files
say "2/4  Installing to $APP_DIR"
mkdir -p "$APP_DIR" || die "could not create $APP_DIR"
cd "$APP_DIR" || die "could not enter $APP_DIR"

cat > "$APP_DIR/email_to_telegram.py" <<'FORWARDER_EOF'
__FORWARDER_PY__
FORWARDER_EOF

cat > "$APP_DIR/setup_helper.py" <<'HELPER_EOF'
__HELPER_PY__
HELPER_EOF

if [ -f "$APP_DIR/config.json" ]; then
  info "keeping the existing config.json"
else
  cat > "$APP_DIR/config.json" <<'CONFIG_EOF'
__CONFIG_JSON__
CONFIG_EOF
  info "config.json written"
fi
info "installed (no extra libraries needed)"

# ---------------------------------------------------------------- accounts
say "3/4  Signing in"
"$PY" "$APP_DIR/setup_helper.py" || die "sign-in did not finish"

# ---------------------------------------------------------------- service
say "4/4  Starting it in the background"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
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

DOMAIN="gui/$(id -u)"

# Stop any previous copy and wait for it to actually go away: bootout returns
# before the process exits, and bootstrapping over a dying job fails with EIO.
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1
for _ in 1 2 3 4 5 6 7 8 9 10; do
  launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
  sleep 1
done

BOOT_ERR="$(launchctl bootstrap "$DOMAIN" "$PLIST" 2>&1)"
if [ $? -ne 0 ]; then
  BOOT_ERR="$(launchctl load -w "$PLIST" 2>&1)"
  [ $? -eq 0 ] || die "could not register the background service: $BOOT_ERR"
fi

launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 \
  || die "the background service did not register"
info "service registered"

PORT="$("$PY" -c "import json;print(json.load(open('$APP_DIR/config.json')).get('dashboard_port',9876))" 2>/dev/null || echo 9876)"

for _ in 1 2 3 4 5 6 7 8; do
  curl -fsS --max-time 2 "http://localhost:$PORT" >/dev/null 2>&1 && break
  sleep 1
done

if curl -fsS --max-time 2 "http://localhost:$PORT" >/dev/null 2>&1; then
  info "running"
else
  info "not responding yet - check $APP_DIR/forwarder.log"
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
