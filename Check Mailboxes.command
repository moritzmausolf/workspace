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

# Pausing drops matching mail rather than queuing it, and the mark moves on
# regardless, so anything that arrived while paused is gone for good.
paused = not state.get("enabled", True)
print(f"\n  forwarding is {'PAUSED - matching mail is being dropped' if paused else 'on'}")
print(f"  last checked: {state.get('last_check') or 'never'}")
print(f"  forwarded so far: {state.get('forwarded_count', 0)}")

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
            typ, data = box.uid("search", None, "ALL")
            uids = data[0].split() if typ == "OK" and data and data[0] else []
        except Exception:
            continue

        # Matched in Python, exactly as the forwarder does. A server-side
        # search would miss a Hide My Email alias, whose header spells the
        # real sender with underscores.
        hits = []
        for uid in uids[-40:]:
            typ, payload = box.uid(
                "fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM)])")
            if typ != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            head = email.message_from_bytes(payload[0][1])
            sender = email.utils.parseaddr(head.get("From", ""))[1].lower()
            if matches(sender, watch):
                hits.append(uid)
        if not hits:
            continue

        here = " (watched)" if folder.upper() == "INBOX" else "  <-- NOT the watched folder"
        print(f"\n  {folder}: {len(hits)} of the last 40 are from these senders{here}")

        for uid in hits[-6:]:
            typ, payload = box.uid("fetch", uid, "(BODY.PEEK[])")
            if typ != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            msg = email.message_from_bytes(payload[0][1])
            sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
            subject = decode_mime_header(msg.get("Subject", ""))[:58]
            past = int(uid) > mark.get("last_uid", 0)
            print(f"    uid {uid.decode():>7}  {msg.get('Date', '')[:31]}")
            print(f"      {subject}")
            print(f"      from {sender[:66]}")
            print(f"      wording matches: {wanted(msg, src)}   newer than mark: {past}")
            if src.get("account_pattern"):
                print(f"      account name: {find_account(msg, src['account_pattern'])}")
    box.logout()

log = Path("forwarder.log")
if log.exists():
    print("\n--- last lines of the log ---")
    for line in log.read_text(errors="replace").splitlines()[-40:]:
        print("  " + line)
PYEOF

"$PY" "$STEP"

echo
echo "--- background services ---"
for L in com.moritz.emailforwarder com.moritz.emailforwarder.menubar; do
  if launchctl print "gui/$(id -u)/$L" >/dev/null 2>&1; then
    echo "  $L: loaded"
  else
    echo "  $L: NOT RUNNING"
  fi
done
echo
printf 'Press return to close.'
read -r _
