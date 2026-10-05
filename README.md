# Email → Telegram forwarder

Watches a mailbox over IMAP and forwards mail from chosen senders into a
Telegram chat, sent from your own Telegram account rather than a bot.

- **Instant** — uses IMAP IDLE, so the server pushes as mail arrives
- **From your account** — Telethon, not the Bot API
- **One-click pause** — a small page at `http://localhost:9876`
- **Always on** — a launchd agent that starts at login

## Install

Run `python3 build_installer.py` to produce **`Setup Email Forwarder.command`**,
then double-click that file in Finder on the target Mac. Terminal opens and the
installer asks for two things: the mailbox password, and the Telegram login code.
It then lists your chats so you can pick the destination by number, sends a test
message, and starts the background service.

Everything lands in `~/EmailForwarder`.

## Configuring the build

`build_installer.py` reads `installer_config.json` (gitignored, since it holds
personal values). Start from the example:

```bash
cp installer_config.example.json installer_config.json
```

| Field | Meaning |
|---|---|
| `imap_server`, `imap_port` | Mail server, e.g. `imap.hostinger.com` / `993` |
| `email` | Mailbox to watch |
| `telegram_api_id`, `telegram_api_hash` | From https://my.telegram.org/apps |
| `telegram_phone` | Your number, with country code |
| `watch_senders` | Addresses to forward; substring match |
| `mode` | `idle` (instant) or `poll` (every 15s) |
| `dashboard_port` | Port for the pause page |

The mailbox password and the destination chat are **not** in this file — the
installer asks for the password and verifies it against the server, and the chat
is picked from a list during setup.

## Running it

| | |
|---|---|
| Pause / resume | `http://localhost:9876` |
| Log | `~/EmailForwarder/forwarder.log` |
| Stop | `launchctl bootout gui/$(id -u)/com.moritz.emailforwarder` |
| Start | `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.moritz.emailforwarder.plist` |
| Remove | stop it, then delete `~/EmailForwarder` and the plist |

Pausing drops matching mail rather than queuing it, so resuming does not replay
a backlog.

## Layout

| File | Role |
|---|---|
| `email_to_telegram.py` | The forwarder: IMAP watcher, Telegram client, pause page |
| `setup_helper.py` | Interactive setup: password check, Telegram sign-in, chat picker |
| `setup_template.sh` | Installer shell, with placeholders for the above |
| `build_installer.py` | Fills the template to produce the `.command` file |
