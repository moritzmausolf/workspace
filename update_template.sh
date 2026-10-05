#!/bin/bash
# Updates an existing EmailForwarder install in place. No sign-in.

set -u
APP_DIR="$HOME/EmailForwarder"
DOMAIN="gui/$(id -u)"
LABEL="com.moritz.emailforwarder"
MENU_LABEL="com.moritz.emailforwarder.menubar"

die() { printf '\n\033[31m%s\033[0m\n\n' "$*"; printf 'Press return to close.'; read -r _; exit 1; }

clear
echo "=== Updating Email Forwarder ==="
echo
[ -f "$APP_DIR/config.json" ] || die "No install found at $APP_DIR - run the full installer first."

cat > "$APP_DIR/email_to_telegram.py" <<'FORWARDER_EOF'
__FORWARDER_PY__
FORWARDER_EOF

cat > "$APP_DIR/menubar_toggle.swift" <<'MENUBAR_EOF'
__MENUBAR_SWIFT__
MENUBAR_EOF

chmod 600 "$APP_DIR/config.json"
echo "  Password file locked to your user only."

if command -v swiftc >/dev/null 2>&1; then
  ERR="$(swiftc -O -o "$APP_DIR/menubar_toggle" "$APP_DIR/menubar_toggle.swift" -framework Cocoa 2>&1)" \
    || die "Menu bar compile failed: $ERR"
  echo "  Menu bar icon rebuilt."
fi

launchctl kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1 || die "Could not restart the forwarder."
launchctl kickstart -k "$DOMAIN/$MENU_LABEL" >/dev/null 2>&1
echo "  Restarted."
echo
echo "  Done."
echo
printf 'Press return to close.'
read -r _
