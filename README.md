# Email-to-Telegram Forwarder

Monitors your Hostinger email and instantly forwards emails from specific senders to a Telegram chat — sent as **you**, not a bot.

## Features

- **Near-instant** — uses IMAP IDLE (push notifications), no polling delay
- **Sends as your account** — messages appear from you in the chat (via Telethon)
- **One-click on/off** — web dashboard at `http://localhost:9876` (bookmark in Arc)
- **Runs in background** — installs as a macOS service, survives reboots

## Setup

### 1. Get Telegram API credentials

1. Go to https://my.telegram.org/apps
2. Log in with your phone number
3. Create an app (name doesn't matter — e.g. "Email Forwarder")
4. Copy the **api_id** and **api_hash**

### 2. Find the target chat ID

The easiest way:
1. Open Telegram Web (https://web.telegram.org)
2. Open the chat you want to forward emails to
3. Look at the URL — the number after `#` is the chat ID
   - For groups it looks like `-1001234567890`
   - For a private chat with someone, it's their user ID

Or: run `python3 get_chat_id.py` after step 3 below (it lists your recent chats).

### 3. Configure

```bash
cp config.example.json config.json
```

Edit `config.json`:

| Field | Value |
|-------|-------|
| `email` | Your Hostinger email address |
| `password` | Your Hostinger email password |
| `telegram_api_id` | From step 1 (a number) |
| `telegram_api_hash` | From step 1 (a hex string) |
| `telegram_phone` | Your phone number with country code, e.g. `+491234567890` |
| `telegram_chat_id` | From step 2 |
| `watch_senders` | List of sender email addresses to forward |

### 4. Install

```bash
bash install_mac.sh
```

On first run, Telegram sends a login code to your phone — enter it in the terminal. After that, the session is saved and no further login is needed.

### 5. Bookmark the dashboard

Open `http://localhost:9876` in Arc and bookmark it.
Click the bookmark anytime to pause/resume.

## Usage

- **Toggle on/off**: Visit `http://localhost:9876`
- **View logs**: `tail -f forwarder.log`
- **Stop**: `launchctl unload ~/Library/LaunchAgents/com.email-forwarder.plist`
- **Start**: `launchctl load ~/Library/LaunchAgents/com.email-forwarder.plist`
- **Uninstall**: `launchctl unload ~/Library/LaunchAgents/com.email-forwarder.plist && rm ~/Library/LaunchAgents/com.email-forwarder.plist`
