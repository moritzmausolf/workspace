#!/bin/bash
# Points the forwarder at a different Telegram chat. No email sign-in.

set -u
APP_DIR="$HOME/EmailForwarder"
LABEL="com.moritz.emailforwarder"

die() { printf '\n\033[31m%s\033[0m\n\n' "$*"; printf 'Press return to close.'; read -r _; exit 1; }

clear
echo "=== Change Telegram chat ==="
[ -f "$APP_DIR/config.json" ] || die "No install found at $APP_DIR - run the full installer first."

PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [ -x "$c" ] && { PY="$c"; break; }
done
[ -n "$PY" ] || die "Python 3 not found."

cd "$APP_DIR" || die "Could not open $APP_DIR"

# Written to a file rather than piped in: reading the program from stdin would
# leave the prompts below with nothing to read from.
STEP="$APP_DIR/.change_chat.py"
trap 'rm -f "$STEP"' EXIT
cat > "$STEP" <<'PYEOF'
import json, sys, time
from pathlib import Path
from email_to_telegram import TelegramError, call_api

path = Path("config.json")
cfg = json.loads(path.read_text())
token = cfg["telegram_bot_token"]

def ask(prompt):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\n  Cancelled.")

def api(method, params):
    # A brief network hiccup should not end the whole step.
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

bot = api("getMe", {})["username"]
try:
    current = name_of(api("getChat", {"chat_id": cfg["telegram_chat_id"]}))
except TelegramError:
    current = cfg.get("telegram_chat_id") or "none"

print(f"\n  Codes currently go to: {current}\n")
print("  In Telegram, open the NEW chat, then:")
print(f"    - group: add @{bot} to it, then send  /start@{bot}  in the group")
print(f"    - just you: open @{bot} and press Start")
print()

# A webhook left over from anything else makes getUpdates fail outright.
try:
    api("deleteWebhook", {})
except TelegramError:
    pass

chats = {}
while not chats:
    ask("  Press return once you have sent /start there ")
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
        if ask("  Type 'id' to enter a chat ID by hand, or return to retry: ") == "id":
            print("\n  To find a group ID: forward any message from the group to")
            print("  @JsonDumpBot - it replies with the chat id (groups start with -100).")
            chat_id = ask("\n  Chat ID: ")
            name = chat_id
            break
else:
    chats = list(chats.items())
    print()
    for i, (_cid, (nm, kind)) in enumerate(chats, 1):
        print(f"   {i:>3}.  {nm[:44]:<44} {kind}")
    print()
    while True:
        choice = ask(f"  Send codes to which one? (1-{len(chats)}): ")
        if choice.isdigit() and 1 <= int(choice) <= len(chats):
            chat_id, (name, _kind) = chats[int(choice) - 1]
            break
        print("  Enter one of the numbers above.")

try:
    api("sendMessage", {"chat_id": chat_id, "parse_mode": "HTML",
                        "text": "<b>Email codes will arrive here from now on.</b>"})
except TelegramError as exc:
    sys.exit(f"  The bot cannot post in that chat: {exc}")

cfg["telegram_chat_id"] = str(chat_id)
path.write_text(json.dumps(cfg, indent=2) + "\n")
path.chmod(0o600)
print(f"\n  Switched to: {name}")
PYEOF

"$PY" "$STEP" || die "Chat was not changed."

launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || die "Saved, but could not restart the forwarder."
echo "  Forwarder restarted."
echo
printf 'Press return to close.'
read -r _
