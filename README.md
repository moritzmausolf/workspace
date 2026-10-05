# Email-to-Telegram Forwarder

Monitors your Hostinger email and instantly forwards emails from specific senders to a Telegram chat.

## Features

- **Near-instant** — uses IMAP IDLE (push notifications), no polling delay
- **One-click on/off** — web dashboard at `http://localhost:9876` (bookmark in Arc)
- **Runs in background** — installs as a macOS service, survives reboots
- **Zero dependencies** — pure Python 3, no pip install needed

## Setup

### 1. Get your Telegram Bot token and Chat ID

You already have your bot (`arm64`). To get the chat ID for your target chat:

1. Add the bot to the Telegram chat you want to forward emails to
2. Send a message in that chat
3. Open `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` in a browser
4. Find `"chat":{"id": ...}` — that number is your chat ID (it's negative for groups)

### 2. Configure

```bash
cp config.example.json config.json
```

Edit `config.json` with your details:

| Field | Value |
|-------|-------|
| `imap_server` | `imap.hostinger.com` (already set) |
| `email` | Your Hostinger email address |
| `password` | Your Hostinger email password |
| `telegram_bot_token` | Your bot token from @BotFather |
| `telegram_chat_id` | The chat ID from step 1 |
| `watch_senders` | List of sender email addresses to forward |

### 3. Install on your Mac

```bash
bash install_mac.sh
```

This installs a background service that starts automatically on login.

### 4. Bookmark the dashboard

Open `http://localhost:9876` in Arc and bookmark it.
Click the bookmark anytime to pause/resume the forwarder.

## Usage

- **Toggle on/off**: Visit `http://localhost:9876` and click the button
- **View logs**: `tail -f forwarder.log`
- **Stop service**: `launchctl unload ~/Library/LaunchAgents/com.email-forwarder.plist`
- **Start service**: `launchctl load ~/Library/LaunchAgents/com.email-forwarder.plist`
- **Uninstall**: `launchctl unload ~/Library/LaunchAgents/com.email-forwarder.plist && rm ~/Library/LaunchAgents/com.email-forwarder.plist`
