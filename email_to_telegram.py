#!/usr/bin/env python3
"""
Email-to-Telegram forwarder.

Watches an IMAP mailbox and forwards mail from configured senders into a
Telegram chat through the Bot API. Standard library only.

Dashboard (pause/resume) at http://localhost:<dashboard_port>.
"""

import email
import email.utils
import html
import imaplib
import json
import re
import signal
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from email.header import decode_header
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
STATE_PATH = BASE / "state.json"

TELEGRAM_LIMIT = 4096
BODY_LIMIT = 3000
IDLE_SECONDS = 240
SEND_ATTEMPTS = 3


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print(f"[{now()}] {msg}", flush=True)


# --------------------------------------------------------------------------
# config + state
# --------------------------------------------------------------------------

def load_config():
    if not CONFIG_PATH.exists():
        log(f"ERROR: {CONFIG_PATH} not found.")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


_lock = threading.Lock()


def _blank_state():
    return {"enabled": True, "last_check": None, "forwarded_count": 0, "seen_uids": []}


def load_state():
    if STATE_PATH.exists():
        try:
            s = _blank_state()
            s.update(json.loads(STATE_PATH.read_text()))
            return s
        except (OSError, ValueError):
            pass
    return _blank_state()


state = load_state()
seen_uids = set(state.get("seen_uids", []))


def save_state():
    state["seen_uids"] = sorted(seen_uids, key=int)[-500:]
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_PATH)


# --------------------------------------------------------------------------
# telegram bot api
# --------------------------------------------------------------------------

class TelegramError(Exception):
    pass


def call_api(token, method, params, timeout=20):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read())
        except Exception:
            raise TelegramError(f"HTTP {exc.code}") from exc
        raise TelegramError(payload.get("description", f"HTTP {exc.code}"))
    except Exception as exc:
        raise TelegramError(str(exc)) from exc

    if not payload.get("ok"):
        raise TelegramError(payload.get("description", "unknown error"))
    return payload["result"]


def send_message(token, chat_id, text):
    """Send one message, retrying transient failures and honouring rate limits."""
    for attempt in range(1, SEND_ATTEMPTS + 1):
        try:
            return call_api(token, "sendMessage", {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            })
        except TelegramError as exc:
            message = str(exc)
            wait = re.search(r"retry after (\d+)", message, re.I)
            if wait:
                delay = int(wait.group(1)) + 1
                log(f"Telegram rate limit, waiting {delay}s")
                time.sleep(delay)
                continue
            if attempt == SEND_ATTEMPTS:
                raise
            log(f"Telegram send failed ({message}), retrying")
            time.sleep(2 * attempt)
    raise TelegramError("exhausted retries")


# --------------------------------------------------------------------------
# email formatting
# --------------------------------------------------------------------------

def decode_mime_header(raw):
    out = []
    for part, charset in decode_header(raw or ""):
        if isinstance(part, bytes):
            out.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(part)
    return "".join(out).strip()


def strip_html(raw):
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</p\s*>", "\n\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = "\n".join(line.strip() for line in raw.splitlines())
    return re.sub(r"\n{3,}", "\n\n", raw).strip()


def extract_body(msg):
    plain = rich = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart" or part.get_filename():
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            if part.get_content_type() == "text/plain" and not plain:
                plain = text
            elif part.get_content_type() == "text/html" and not rich:
                rich = text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                rich = text
            else:
                plain = text

    body = plain.strip() or strip_html(rich)
    if len(body) > BODY_LIMIT:
        body = body[:BODY_LIMIT].rstrip() + "\n\n[...truncated]"
    return body.strip()


def format_message(msg):
    sender = decode_mime_header(msg.get("From", "Unknown"))
    subject = decode_mime_header(msg.get("Subject", "(no subject)"))
    text = (
        f"<b>{html.escape(subject)}</b>\n"
        f"<i>from {html.escape(sender)}</i>\n\n"
        f"{html.escape(extract_body(msg))}"
    )
    if len(text) > TELEGRAM_LIMIT:
        text = text[: TELEGRAM_LIMIT - 20].rstrip() + "\n[...truncated]"
    return text


# --------------------------------------------------------------------------
# imap
# --------------------------------------------------------------------------

def connect_imap(cfg):
    mail = imaplib.IMAP4_SSL(cfg["imap_server"], cfg.get("imap_port", 993))
    mail.login(cfg["email"], cfg["password"])
    mail.select("INBOX")
    return mail


def matches(sender, watch):
    return any(w == sender or w in sender for w in watch)


def check_mailbox(mail, cfg):
    watch = [s.lower().strip() for s in cfg["watch_senders"]]
    typ, data = mail.uid("search", None, "UNSEEN")
    if typ != "OK" or not data or not data[0]:
        return

    changed = False
    for uid in data[0].split():
        uid_str = uid.decode()
        if uid_str in seen_uids:
            continue

        typ, payload = mail.uid("fetch", uid, "(BODY.PEEK[])")
        if typ != "OK" or not payload or not isinstance(payload[0], tuple):
            continue

        msg = email.message_from_bytes(payload[0][1])
        sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()

        if not matches(sender, watch):
            seen_uids.add(uid_str)
            continue

        with _lock:
            enabled = state["enabled"]

        if not enabled:
            seen_uids.add(uid_str)
            changed = True
            log(f"Paused - dropping mail from {sender}")
            continue

        log(f"Forwarding from {sender}: {decode_mime_header(msg.get('Subject', ''))}")
        try:
            send_message(cfg["telegram_bot_token"], cfg["telegram_chat_id"],
                         format_message(msg))
        except TelegramError as exc:
            log(f"Could not send ({exc}) - will retry on the next pass")
            continue

        seen_uids.add(uid_str)
        with _lock:
            state["forwarded_count"] += 1
        changed = True
        log("Sent")

    if changed:
        with _lock:
            save_state()


def idle_wait(mail, seconds):
    tag = mail._new_tag().decode()
    mail.send(f"{tag} IDLE\r\n".encode())
    mail.readline()
    previous = mail.sock.gettimeout()
    mail.sock.settimeout(seconds)
    try:
        while True:
            line = mail.readline().decode(errors="replace")
            if not line:
                raise imaplib.IMAP4.abort("connection closed during IDLE")
            if "EXISTS" in line or "RECENT" in line or line.startswith(tag):
                break
    except (socket.timeout, TimeoutError):
        pass
    finally:
        mail.sock.settimeout(previous)
        try:
            mail.send(b"DONE\r\n")
            mail.readline()
        except Exception:
            pass


def supports_idle(mail):
    caps = mail.capabilities or ()
    return any((c.decode() if isinstance(c, bytes) else c).upper() == "IDLE" for c in caps)


def watch_mailbox(cfg):
    want_idle = cfg.get("mode", "idle") != "poll"
    while True:
        mail = None
        try:
            log(f"Connecting to {cfg['imap_server']} ...")
            mail = connect_imap(cfg)
            use_idle = want_idle and supports_idle(mail)
            log("Connected - " + ("IDLE, instant" if use_idle else "polling every 15s"))

            while True:
                check_mailbox(mail, cfg)
                with _lock:
                    state["last_check"] = now()
                    save_state()
                if use_idle:
                    idle_wait(mail, IDLE_SECONDS)
                else:
                    time.sleep(15)
                mail.noop()

        except Exception as exc:
            log(f"Mailbox error: {exc} - reconnecting in 10s")
            time.sleep(10)
        finally:
            if mail is not None:
                try:
                    mail.logout()
                except Exception:
                    pass


# --------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Email Forwarder</title>
<style>
:root{--bg:#fafafa;--fg:#18181b;--muted:#71717a;--card:#fff;--line:#e4e4e7;
--on:#16a34a;--off:#dc2626}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
--bg:#09090b;--fg:#fafafa;--muted:#a1a1aa;--card:#18181b;--line:#27272a;
--on:#4ade80;--off:#f87171}}
*{margin:0;padding:0;box-sizing:border-box}
body{font:16px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
background:var(--bg);color:var(--fg);min-height:100vh;
display:flex;align-items:center;justify-content:center;padding:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;
padding:28px;width:100%;max-width:360px;text-align:center}
h1{font-size:13px;font-weight:600;letter-spacing:.06em;margin-bottom:18px;color:var(--muted)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;
vertical-align:middle;background:var(--STATE)}
.state{font-size:22px;font-weight:600;margin-bottom:22px}
button{width:100%;padding:14px;border:0;border-radius:11px;font-size:16px;
font-weight:600;cursor:pointer;background:var(--BTN);color:#fff;font-family:inherit}
button:active{transform:scale(.985)}
.meta{margin-top:18px;font-size:13px;color:var(--muted);line-height:1.7}
</style></head><body>
<div class="card">
  <h1>EMAIL &rarr; TELEGRAM</h1>
  <div class="state"><span class="dot"></span>__STATE__</div>
  <button onclick="t()">__BTN__</button>
  <div class="meta">__COUNT__ forwarded<br>last checked __LAST__</div>
</div>
<script>
async function t(){await fetch('/toggle',{method:'POST'});location.reload()}
setTimeout(()=>location.reload(),30000);
</script></body></html>"""


class Dashboard(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        with _lock:
            enabled, count = state["enabled"], state["forwarded_count"]
            last = state["last_check"] or "never"
        body = (PAGE
                .replace("var(--STATE)", "var(--on)" if enabled else "var(--off)")
                .replace("var(--BTN)", "var(--off)" if enabled else "var(--on)")
                .replace("__STATE__", "Running" if enabled else "Paused")
                .replace("__BTN__", "Pause" if enabled else "Resume")
                .replace("__COUNT__", str(count))
                .replace("__LAST__", last)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/toggle":
            self.send_response(404)
            self.end_headers()
            return
        with _lock:
            state["enabled"] = not state["enabled"]
            save_state()
            log("Forwarder " + ("resumed" if state["enabled"] else "paused"))
        self.send_response(204)
        self.end_headers()


# --------------------------------------------------------------------------

def main():
    cfg = load_config()
    required = ["imap_server", "email", "password",
                "telegram_bot_token", "telegram_chat_id", "watch_senders"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        log(f"ERROR: config.json is missing: {', '.join(missing)}")
        sys.exit(1)

    bot = call_api(cfg["telegram_bot_token"], "getMe", {})
    log(f"Telegram bot: @{bot.get('username')}")

    port = cfg.get("dashboard_port", 9876)
    server = HTTPServer(("127.0.0.1", port), Dashboard)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"Dashboard: http://localhost:{port}")
    log("Watching for mail from: " + ", ".join(cfg["watch_senders"]))

    def stop(_sig, _frame):
        log("Shutting down")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    watch_mailbox(cfg)


if __name__ == "__main__":
    main()
