#!/bin/bash
# Install the Email-to-Telegram forwarder as a background service on macOS
# Usage: bash install_mac.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.email-forwarder.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"
PYTHON="$(which python3)"

echo "📧 → 💬 Email-to-Telegram Forwarder Installer"
echo "================================================"

# Install Telethon
echo "Installing Telethon..."
pip3 install telethon --quiet

# Check config exists
if [ ! -f "$SCRIPT_DIR/config.json" ]; then
    echo ""
    echo "⚠️  config.json not found!"
    echo "   Copy the example and fill in your details:"
    echo ""
    echo "   cp config.example.json config.json"
    echo "   nano config.json"
    echo ""
    echo "Then run this script again."
    exit 1
fi

# Create launchd plist
cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$SCRIPT_DIR/email_to_telegram.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/forwarder.log</string>
    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/forwarder.log</string>
</dict>
</plist>
EOF

# First run — must be interactive so you can enter the Telegram login code
echo ""
echo "First run: logging into Telegram (you'll get a code on your phone)..."
echo ""
$PYTHON "$SCRIPT_DIR/email_to_telegram.py" --login-only 2>&1 || true

# Load the service
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo ""
echo "Forwarder installed and running!"
echo ""
echo "   Dashboard:  http://localhost:9876"
echo "   Logs:       $SCRIPT_DIR/forwarder.log"
echo ""
echo "   To stop:    launchctl unload $PLIST_PATH"
echo "   To start:   launchctl load $PLIST_PATH"
echo "   To uninstall: launchctl unload $PLIST_PATH && rm $PLIST_PATH"
echo ""
echo "💡 Bookmark http://localhost:9876 in Arc for one-click on/off!"
