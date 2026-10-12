#!/bin/bash
# Read-only: lists the most recent mail in every folder of each configured
# mailbox, so the real sender address can be seen. Changes nothing.

set -u
APP_DIR="$HOME/EmailForwarder"

die() { printf '\n\033[31m%s\033[0m\n\n' "$*"; printf 'Press return to close.'; read -r _; exit 1; }

clear
echo "=== Recent mail ==="
[ -f "$APP_DIR/config.json" ] || die "No install found at $APP_DIR."

PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [ -x "$c" ] && { PY="$c"; break; }
done
[ -n "$PY" ] || die "Python 3 not found."

cd "$APP_DIR" || die "Could not open $APP_DIR"

STEP="$APP_DIR/.show_recent.py"
trap 'rm -f "$STEP"' EXIT
cat > "$STEP" <<'PYEOF'
import email
import imaplib
import json
import re
import sys
from pathlib import Path

from email_to_telegram import decode_mime_header, sources

cfg = json.loads(Path("config.json").read_text())
only = sys.argv[1].lower() if len(sys.argv) > 1 else ""

for src in sources(cfg):
    if only and only not in src["email"].lower() and only not in src["name"].lower():
        continue
    print(f"\n=== {src['name']}  ({src['email']}) ===")
    try:
        box = imaplib.IMAP4_SSL(src["imap_server"], src.get("imap_port", 993))
        box.login(src["email"], src["password"])
    except Exception as exc:
        print(f"  COULD NOT SIGN IN: {exc}")
        continue

    try:
        typ, folders = box.list()
    except Exception as exc:
        print(f"  could not list folders: {exc}")
        folders = []

    names = []
    for raw in folders or []:
        line = raw.decode(errors="replace")
        found = re.search(r'"([^"]*)"\s*$', line) or re.search(r'(\S+)\s*$', line)
        if found and "\\Noselect" not in line:
            names.append(found.group(1))
    print(f"  folders: {', '.join(names) or '(none listed)'}")

    for folder in names:
        try:
            typ, data = box.select(f'"{folder}"', readonly=True)
            if typ != "OK":
                continue
            typ, found = box.uid("search", None, "ALL")
            uids = found[0].split() if typ == "OK" and found and found[0] else []
        except Exception:
            continue
        if not uids:
            continue
        print(f"\n  --- {folder}: {len(uids)} message(s), newest 8 ---")
        for uid in uids[-8:]:
            typ, payload = box.uid(
                "fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            head = email.message_from_bytes(payload[0][1])
            frm = decode_mime_header(head.get("From", ""))
            sub = decode_mime_header(head.get("Subject", ""))
            flag = "  <== reddit" if "reddit" in frm.lower() else ""
            print(f"    {head.get('Date', '')[:31]}{flag}")
            print(f"      from: {frm[:72]}")
            print(f"      subj: {sub[:72]}")
    box.logout()
PYEOF

"$PY" "$STEP" "${1:-}"
echo
printf 'Press return to close.'
read -r _
