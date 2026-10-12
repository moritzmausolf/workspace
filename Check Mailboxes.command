#!/bin/bash
# Read-only check: can each mailbox be reached, and would its recent mail be
# forwarded? Changes nothing.

set -u
APP_DIR="$HOME/EmailForwarder"

die() { printf '\n\033[31m%s\033[0m\n\n' "$*"; printf 'Press return to close.'; read -r _; exit 1; }

clear
echo "=== Mailbox check ==="
[ -f "$APP_DIR/config.json" ] || die "No install found at $APP_DIR."

PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [ -x "$c" ] && { PY="$c"; break; }
done
[ -n "$PY" ] || die "Python 3 not found."

cd "$APP_DIR" || die "Could not open $APP_DIR"

STEP="$APP_DIR/.check_mailboxes.py"
trap 'rm -f "$STEP"' EXIT
cat > "$STEP" <<'PYEOF'
import email
import imaplib
import json
import re
from pathlib import Path

from email_to_telegram import (decode_mime_header, matches, sources, state,
                               watch_list, wanted, find_account)

cfg = json.loads(Path("config.json").read_text())
marks = state.get("sources", {})

for src in sources(cfg):
    print(f"\n--- {src['name']}  ({src['email']}) ---")
    watch = watch_list(src)
    print(f"  senders: {', '.join(watch)}")
    if src.get("must_contain"):
        print(f"  only when it says: {src['must_contain']!r}")
    key = f"{src['imap_server']}/{src['email']}"
    mark = marks.get(key, {})
    print(f"  forwarded up to uid {mark.get('last_uid', 0)}")

    try:
        box = imaplib.IMAP4_SSL(src["imap_server"], src.get("imap_port", 993))
        box.login(src["email"], src["password"])
    except Exception as exc:
        print(f"  COULD NOT SIGN IN: {exc}")
        continue
    print("  signed in")

    # Where does this sender's mail actually land? A rule may move it.
    try:
        typ, folders = box.list()
        names = []
        for raw in folders or []:
            line = raw.decode(errors="replace")
            found = re.search(r'"([^"]*)"$', line) or re.search(r'(\S+)$', line)
            if found:
                names.append(found.group(1))
    except Exception:
        names = ["INBOX"]

    for folder in names:
        try:
            typ, _ = box.select(f'"{folder}"', readonly=True)
            if typ != "OK":
                continue
            hits = []
            for entry in watch:
                typ, data = box.uid("search", None, "FROM", f'"{entry}"')
                if typ == "OK" and data and data[0]:
                    hits += data[0].split()
        except Exception:
            continue
        if not hits:
            continue
        here = " (watched)" if folder.upper() == "INBOX" else "  <-- NOT the watched folder"
        print(f"\n  {folder}: {len(set(hits))} mail from these senders{here}")

        for uid in sorted(set(hits), key=int)[-4:]:
            typ, payload = box.uid("fetch", uid, "(BODY.PEEK[])")
            if typ != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            msg = email.message_from_bytes(payload[0][1])
            sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
            subject = decode_mime_header(msg.get("Subject", ""))[:58]
            ok_from = matches(sender, watch)
            ok_text = wanted(msg, src)
            past = int(uid) > mark.get("last_uid", 0)
            print(f"    uid {uid.decode():>7}  {msg.get('Date', '')[:31]}")
            print(f"      {subject}")
            print(f"      sender matches: {ok_from}   wording matches: {ok_text}"
                  f"   newer than mark: {past}")
            if src.get("account_pattern"):
                print(f"      account name: {find_account(msg, src['account_pattern'])}")
    box.logout()

log = Path("forwarder.log")
if log.exists():
    print("\n--- last lines of the log ---")
    for line in log.read_text(errors="replace").splitlines()[-25:]:
        print("  " + line)
PYEOF

"$PY" "$STEP"
echo
printf 'Press return to close.'
read -r _
