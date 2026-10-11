# Email → Telegram forwarder

Watches IMAP mailboxes and forwards mail from chosen senders into Telegram
chats. Python standard library only — no pip, no venv. Runs on the owner's
MacBook as a launchd agent; this repository is the source it is built from.

Read `README.md` for how it works. This file is what a fresh session needs to
avoid relearning the sharp edges.

## Layout

| File | Role |
|---|---|
| `email_to_telegram.py` | The forwarder: IMAP watchers, Bot API client, pause page |
| `menubar_toggle.swift` | macOS menu bar icon, compiled with `swiftc` at install |
| `setup_helper.py` | Interactive setup: mailbox check, bot token, chat picker |
| `setup_template.sh` | Installer shell, with placeholders for the above |
| `update_template.sh` | Update shell: replaces the forwarder, keeps the config |
| `build_installer.py` | Fills both templates to produce the `.command` files |
| `Add Mailbox.command` | Adds another mailbox, with its own senders and chat |
| `Change Telegram Chat.command` | Re-points one mailbox, or all of them |
| `Add Menu Bar Icon.command` | Compiles and starts just the menu bar icon |
| `ready-to-run/` | Already-built installers, from the last `build_installer.py` run |

## Building

```bash
python3 build_installer.py
```

Reads `installer_config.json` and writes `Setup Email Forwarder.command` and
`Update Email Forwarder.command`. Everything is embedded in those single files
via heredocs, so they are self-contained and double-clickable in Finder.

`installer_config.json` holds the mailbox address and senders. It holds **no**
password, bot token or chat id: `build_installer.py` blanks those and the
installer collects them interactively, verifying each before writing it.

## Live setup on the owner's Mac

Installed at `~/EmailForwarder`, with two launchd agents:
`com.moritz.emailforwarder` and `com.moritz.emailforwarder.menubar`.

Two mailboxes, both posting into one topic of a Telegram forum group:

- **Hostinger** — six-digit verification codes from `no-reply@app.redgifs.com`
- **iCloud** — Reddit ban notices: sender `redditmail.com`, narrowed with
  `must_contain: "You have been permanently banned"`

## Config shape

`config.json` lives beside the forwarder at `~/EmailForwarder`, is `chmod 600`,
and is never in this repository. Several mailboxes go in a `sources` list:

```json
{
  "telegram_bot_token": "...",
  "dashboard_port": 9876,
  "sources": [
    {"name": "Arc codes", "imap_server": "imap.hostinger.com", "imap_port": 993,
     "email": "...", "password": "...", "watch_senders": ["no-reply@app.redgifs.com"],
     "telegram_chat_id": "-100...", "telegram_topic_id": 42,
     "code_pattern": "\\b(\\d{6})\\b"},
    {"name": "Reddit bans", "imap_server": "imap.mail.me.com", "imap_port": 993,
     "email": "...@icloud.com", "password": "...", "watch_senders": ["redditmail.com"],
     "telegram_chat_id": "-100...", "telegram_topic_id": 42,
     "must_contain": "You have been permanently banned"}
  ]
}
```

A pre-`sources` config describing one mailbox at the top level is still read as
a single source, and its position in the mailbox is carried over, so an
existing install survives an update untouched.

`enabled`, `forwarded_count` and `last_check` stay shared in `state.json`, so
one click on the menu bar icon pauses every mailbox. Each mailbox keeps its own
high-water mark under `state["sources"]`, keyed by server and address.

## Things that will bite you

- **`code_pattern` must never be inherited between sources.** A six-digit
  pattern meant for one mailbox would otherwise reduce another mailbox's mail
  to a stray number from its body. Only `imap_port` and `mode` are inherited.
- **Never run an interactive step as `python3 - <<'EOF'`.** The program arrives
  on stdin, so stdin is already at EOF and the first `input()` raises, which
  the prompt helpers read as Ctrl-C. Write the step to a file and run that.
- **A group with topics needs `message_thread_id`.** Without it every message
  lands in the group's General topic rather than the chosen one.
- **A topic is only discoverable through `getUpdates` once `/start` is sent
  inside it.** The scripts therefore also accept a pasted message link, whose
  middle number is the topic when a message number follows it.
- **A plain `/start` in a group is often never delivered** — Telegram only
  passes it on if that bot was the last bot to post there. Tell people to send
  `/start@thebotname`.
- **Only chats the bot is a member of can appear in discovery.** A `/start` in
  a chat the bot has not joined reaches nobody.
- **`getUpdates` fails outright while a webhook is set**, so clear it with
  `deleteWebhook` before polling.
- **iCloud rejects normal passwords over IMAP.** It needs an app-specific
  password from account.apple.com, which requires 2FA.
- **Every `.command` file must be executable.** Without the bit macOS refuses to
  run it on a double-click with an access-privileges error, and `zip` preserves
  the bit so it must be right before packaging.

## Never commit

`config.json`, `installer_config.json` beyond its current credential-free form,
`state.json`, `forwarder.log`, or any built `.command`. The repository is
public. Check `.gitignore` before adding files.
