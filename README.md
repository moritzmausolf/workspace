# Email → Telegram forwarder

Watches a mailbox over IMAP and forwards mail from chosen senders into a
Telegram chat.

- **Instant** — uses IMAP IDLE, so the server pushes as mail arrives
- **No dependencies** — Python standard library only, no pip, no venv
- **One-click pause** — a small page at `http://localhost:9876`
- **Always on** — a launchd agent that starts at login

Messages are delivered by a Telegram bot. An earlier version signed in as a
personal account through Telethon; that was dropped because it depends on an
interactive login code that Telegram often declines to deliver, it needs a
third-party library, and automating a personal account risks the account
itself. The Bot API is plain HTTPS and needs no login.

## Install

Run `python3 build_installer.py` to produce **`Setup Email Forwarder.command`**,
then double-click that file in Finder on the target Mac. It asks for three
things: the mailbox password, a bot token, and which chat to post into (picked
from a list). It then sends a test message and starts the background service.

Everything lands in `~/EmailForwarder`.

Because the file arrives via a browser, macOS quarantines it. Either allow it
once under System Settings → Privacy & Security → **Open Anyway**, or strip the
flag directly:

```bash
xattr -cr "Setup Email Forwarder.command" && "./Setup Email Forwarder.command"
```

## Getting a bot

Message **@BotFather** on Telegram, send `/newbot`, answer two prompts, and it
replies with a token. Then open the destination chat, add the bot to it (or
start a direct chat with it) and send `/start` — that is what lets the installer
find the chat.

## Configuring the build

`build_installer.py` reads `installer_config.json`, which is gitignored since it
holds personal values. Start from the example:

```bash
cp installer_config.example.json installer_config.json
```

| Field | Meaning |
|---|---|
| `imap_server`, `imap_port` | Mail server, e.g. `imap.hostinger.com` / `993` |
| `email` | Mailbox to watch |
| `watch_senders` | Addresses to forward; substring match |
| `mode` | `idle` (instant) or `poll` (every 15s) |
| `dashboard_port` | Port for the pause page |

The mailbox password, bot token and target chat are deliberately **not** here —
the installer collects them and verifies each one before writing it.

## Running it

| | |
|---|---|
| Pause / resume | `http://localhost:9876` |
| Log | `~/EmailForwarder/forwarder.log` |
| Stop | `launchctl bootout gui/$(id -u)/com.moritz.emailforwarder` |
| Start | `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.moritz.emailforwarder.plist` |
| Remove | stop it, then delete `~/EmailForwarder` and the plist |

Pausing drops matching mail rather than queuing it, so resuming does not replay
a backlog. A send that fails is left unmarked and retried on the next pass.

## Layout

| File | Role |
|---|---|
| `email_to_telegram.py` | The forwarder: IMAP watcher, Bot API client, pause page |
| `setup_helper.py` | Interactive setup: mailbox check, bot token, chat picker |
| `setup_template.sh` | Installer shell, with placeholders for the above |
| `build_installer.py` | Fills the template to produce the `.command` file |
