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
import json, re, sys, time
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

# An install with several mailboxes keeps them in a list; an older one holds a
# single mailbox at the top level.
listed = cfg.get("sources") or []
if len(listed) > 1:
    print("\n  Which mailbox should post somewhere else?\n")
    for i, src in enumerate(listed, 1):
        print(f"   {i:>3}.  {src.get('name') or src.get('email')}")
    print("     a.  all of them")
    print()
    while True:
        choice = ask(f"  Which one? (1-{len(listed)}, or a): ").lower()
        if choice == "a":
            targets = listed
            break
        if choice.isdigit() and 1 <= int(choice) <= len(listed):
            targets = [listed[int(choice) - 1]]
            break
        print("  Enter one of the numbers above, or 'a' for all of them.")
else:
    # One mailbox in a list, or an older install holding it at the top level.
    targets = [listed[0]] if listed else [cfg]

if len(targets) > 1:
    label = "All mail"
    print(f"\n  Moving all {len(targets)} mailboxes to one chat.\n")
else:
    label = targets[0].get("name") or "Codes"
    try:
        # Only for display, so one attempt: no need to retry a chat that is gone.
        current = name_of(call_api(token, "getChat",
                                   {"chat_id": targets[0]["telegram_chat_id"]}))
    except (TelegramError, KeyError):
        current = targets[0].get("telegram_chat_id") or "none"
    print(f"\n  {label} currently go to: {current}\n")
print("  In Telegram, open the NEW chat, then:")
print(f"    - group: add @{bot} to it, then send  /start@{bot}  in the group")
print(f"    - a topic inside a group: send  /start@{bot}  in that topic")
print(f"    - just you: open @{bot} and press Start")
print()

# A webhook left over from anything else makes getUpdates fail outright.
try:
    api("deleteWebhook", {})
except TelegramError:
    pass

def parse_link(raw):
    """
    Read a chat, and a topic when there is one, out of a message link.

    In a group with topics a link reads .../<chat>/<topic>/<message>, so the
    middle number only means a topic when a message number follows it.
    """
    raw = raw.strip()
    found = re.search(r"t\.me/c/(\d+)(?:/(\d+))?(?:/(\d+))?", raw)
    if found:
        topic = int(found.group(2)) if found.group(2) and found.group(3) else None
        return int("-100" + found.group(1)), topic
    found = re.search(r"t\.me/([A-Za-z][\w]{3,})(?:/(\d+))?(?:/(\d+))?", raw)
    if found:
        topic = int(found.group(2)) if found.group(2) and found.group(3) else None
        return "@" + found.group(1), topic
    return raw, None


def typed_target():
    """A chat the bot has not posted in yet can still be named by hand."""
    print("\n  In Telegram, right-click a message in that chat or topic and")
    print("  choose 'Copy Message Link', then paste it here. A plain chat id")
    print("  works too (groups start with -100).")
    return parse_link(ask("\n  Link or chat ID: "))


def topic_of(msg):
    """The forum topic a message sits in, when the group has topics turned on."""
    tid = msg.get("message_thread_id")
    if not tid:
        return None, None
    named = ((msg.get("reply_to_message") or {}).get("forum_topic_created")
             or msg.get("forum_topic_created") or {})
    return tid, named.get("name")


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
            msg = u.get(key) or {}
            chat = msg.get("chat")
            if not chat:
                continue
            tid, tname = topic_of(msg)
            shown = name_of(chat)
            if tid:
                shown += "  >  " + (tname or f"topic {tid}")
            chats[(chat["id"], tid)] = (shown, chat.get("type", "chat"))
    if not chats:
        print(f"  Nothing seen yet. In a group, send  /start@{bot}  (with the")
        print("  @name) - a plain /start often never reaches the bot.\n")
        if ask("  Type 'id' to enter a chat by hand, or return to retry: ") == "id":
            chat_id, topic_id = typed_target()
            name = f"{chat_id}" + (f" topic {topic_id}" if topic_id else "")
            break
else:
    chats = list(chats.items())
    print()
    for i, ((_cid, _tid), (nm, kind)) in enumerate(chats, 1):
        print(f"   {i:>3}.  {nm[:48]:<48} {kind}")
    print()
    print(f"  Only chats @{bot} has been used in can appear here. A topic shows")
    print("  up once /start is sent inside that topic; otherwise choose 'id'.")
    while True:
        choice = ask(f"  Which one? (1-{len(chats)}, or 'id' to paste a link): ").lower()
        if choice == "id":
            chat_id, topic_id = typed_target()
            name = f"{chat_id}" + (f" topic {topic_id}" if topic_id else "")
            break
        if choice.isdigit() and 1 <= int(choice) <= len(chats):
            (chat_id, topic_id), (name, _kind) = chats[int(choice) - 1]
            break
        print("  Enter one of the numbers above, or 'id'.")

probe = {"chat_id": chat_id, "parse_mode": "HTML",
         "text": f"<b>{label} will arrive here from now on.</b>"}
if topic_id:
    probe["message_thread_id"] = topic_id
try:
    api("sendMessage", probe)
except TelegramError as exc:
    sys.exit(f"  The bot cannot post there: {exc}")

for target in targets:
    target["telegram_chat_id"] = str(chat_id)
    if topic_id:
        target["telegram_topic_id"] = topic_id
    else:
        target.pop("telegram_topic_id", None)
path.write_text(json.dumps(cfg, indent=2) + "\n")
path.chmod(0o600)
print()
for target in targets:
    print(f"  {target.get('name') or 'Codes'} -> {name}")
PYEOF

"$PY" "$STEP" || die "Chat was not changed."

launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || die "Saved, but could not restart the forwarder."
echo "  Forwarder restarted."
echo
printf 'Press return to close.'
read -r _
