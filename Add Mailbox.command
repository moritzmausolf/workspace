#!/bin/bash
# Adds a second mailbox to the forwarder, with its own senders and its own
# Telegram group. The mailbox already set up keeps working untouched.

set -u
APP_DIR="$HOME/EmailForwarder"
LABEL="com.moritz.emailforwarder"

die() { printf '\n\033[31m%s\033[0m\n\n' "$*"; printf 'Press return to close.'; read -r _; exit 1; }

clear
echo "=== Add a mailbox ==="
[ -f "$APP_DIR/config.json" ] || die "No install found at $APP_DIR - run the full installer first."

grep -q '^def sources(' "$APP_DIR/email_to_telegram.py" 2>/dev/null \
  || die "The installed forwarder only handles one mailbox.
Run 'Update Email Forwarder.command' first, then this script."

PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [ -x "$c" ] && { PY="$c"; break; }
done
[ -n "$PY" ] || die "Python 3 not found."

cd "$APP_DIR" || die "Could not open $APP_DIR"

# Written to a file rather than piped in: reading the program from stdin would
# leave the prompts below with nothing to read from.
STEP="$APP_DIR/.add_mailbox.py"
trap 'rm -f "$STEP"' EXIT
cat > "$STEP" <<'PYEOF'
import getpass
import imaplib
import json
import sys
import time
from pathlib import Path

from email_to_telegram import TelegramError, call_api, sources

path = Path("config.json")
cfg = json.loads(path.read_text())
token = cfg["telegram_bot_token"]


def ask(prompt, default=""):
    try:
        got = input(f"  {prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\n  Cancelled.")
    return got or default


def secret(prompt):
    try:
        return getpass.getpass(f"  {prompt}: ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\n  Cancelled.")


def api(method, params):
    for attempt in range(3):
        try:
            return call_api(token, method, params)
        except TelegramError as exc:
            if attempt == 2:
                raise
            print(f"  Network problem ({exc}), trying again...")
            time.sleep(3)


def name_of(chat):
    return (chat.get("title")
            or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            or chat.get("username") or str(chat["id"]))


existing = sources(cfg)
print("\n  Already watching:")
for src in existing:
    print(f"    - {src['name']}  ({src['email']})")

print("\n  --- The new mailbox ---")
print("  For iCloud this needs an app-specific password from account.apple.com,")
print("  not your normal Apple ID password.\n")

server = ask("IMAP server", "imap.mail.me.com")
address = ask("Email address")
if not address:
    sys.exit("  No address given.")

password = ""
for attempt in range(3):
    password = secret("App-specific password (hidden)")
    if not password:
        continue
    try:
        box = imaplib.IMAP4_SSL(server, 993)
        box.login(address, password)
        box.select("INBOX")
        box.logout()
        print("  Signed in.")
        break
    except imaplib.IMAP4.error:
        print("  Password rejected. For iCloud it must be an app-specific one.\n")
        password = ""
    except Exception as exc:
        sys.exit(f"  Could not reach {server}: {exc}")
if not password:
    sys.exit("  Giving up on the mailbox.")

print()
label = ask("A short name for this mailbox", "Reddit bans")
senders = ask("Forward mail from (comma separated)", "redditmail.com")
needle = ask("Only when the mail contains", "You have been permanently banned")

print("\n  --- Where should it go? ---")
bot = api("getMe", {})["username"]
print(f"  Open the group that should receive these, add @{bot} to it,")
print(f"  then send  /start@{bot}  there.\n")

try:
    api("deleteWebhook", {})
except TelegramError:
    pass

chats = {}
while not chats:
    ask("Press return once you have done that", " ")
    try:
        updates = api("getUpdates", {"limit": 100, "timeout": 0})
    except TelegramError as exc:
        print(f"  Could not reach Telegram: {exc}\n")
        continue
    for u in updates:
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            chat = (u.get(key) or {}).get("chat")
            if chat:
                chats[chat["id"]] = (name_of(chat), chat.get("type", "chat"))
    if not chats:
        print(f"  Nothing seen yet. In a group, send  /start@{bot}  (with the")
        print("  @name) - a plain /start often never reaches the bot.\n")
        if ask("Type 'id' to enter a chat ID by hand, or return to retry", " ") == "id":
            print("\n  To find a group ID: forward any message from the group to")
            print("  @JsonDumpBot - it replies with the chat id (groups start with -100).")
            chat_id = ask("Chat ID")
            where = chat_id
            break
else:
    listed = list(chats.items())
    print()
    for i, (_cid, (nm, kind)) in enumerate(listed, 1):
        print(f"   {i:>3}.  {nm[:44]:<44} {kind}")
    print()
    while True:
        choice = ask(f"Which one? (1-{len(listed)})")
        if choice.isdigit() and 1 <= int(choice) <= len(listed):
            chat_id, (where, _kind) = listed[int(choice) - 1]
            break
        print("  Enter one of the numbers above.")

if str(chat_id) in {str(s.get("telegram_chat_id")) for s in existing}:
    print("\n  Note: that is the same group an existing mailbox already posts to.")

new = {
    "name": label,
    "imap_server": server,
    "imap_port": 993,
    "email": address,
    "password": password,
    "watch_senders": [s.strip() for s in senders.split(",") if s.strip()],
    "telegram_chat_id": str(chat_id),
    "code_pattern": "",
}
if needle:
    new["must_contain"] = needle

try:
    api("sendMessage", {"chat_id": chat_id, "parse_mode": "HTML",
                        "text": f"<b>{label} will arrive here from now on.</b>"})
except TelegramError as exc:
    sys.exit(f"  The bot cannot post in that chat: {exc}")

# Fold the single-mailbox shape into the list before appending to it.
cfg["sources"] = existing + [new]
for moved in ("imap_server", "imap_port", "email", "password", "watch_senders",
              "telegram_chat_id", "code_pattern", "must_contain", "name"):
    cfg.pop(moved, None)

path.write_text(json.dumps(cfg, indent=2) + "\n")
path.chmod(0o600)
print(f"\n  Added '{label}' -> {where}")
print(f"  Now watching {len(cfg['sources'])} mailboxes.")
PYEOF

"$PY" "$STEP" || die "Nothing was changed."

launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || die "Saved, but could not restart the forwarder."
echo "  Forwarder restarted."
echo
printf 'Press return to close.'
read -r _
