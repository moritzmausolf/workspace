#!/usr/bin/env python3
"""
Email-to-Telegram Forwarder.

Watches an IMAP mailbox and forwards mail from configured senders into a
Telegram chat, sent from the user's own account via Telethon.

Dashboard (pause/resume) at http://localhost:<dashboard_port>.
"""

import asyncio
import email
import email.utils
import html
import imaplib
import json
import signal
import socket
import sys
import threading
import time
from datetime import datetime
from email.header import decode_header
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from telethon import TelegramClient

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
STATE_PATH = BASE / "state.json"
SESSION_PATH = BASE / "telegram_session"

TELEGRAM_LIMIT = 4096
BODY_LIMIT = 3000
IDLE_SECONDS = 240


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


_state_lock = threading.Lock()


def _default_state():
    return {"enabled": True, "last_check": None, "forwarded_count": 0, "seen_uids": []}


def load_state():
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH) as f:
                s = _default_state()
                s.update(json.load(f))
                return s
        except (OSError, ValueError):
            pass
    return _default_state()


state = load_state()
# Keep the on-disk UID list bounded; IMAP UIDs only ever increase.
seen_uids = set(state.get("seen_uids", []))


def save_state():
    state["seen_uids"] = sorted(seen_uids)[-500:]
    tmp = STATE_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(STATE_PATH)


# --------------------------------------------------------------------------
# telegram
# --------------------------------------------------------------------------

class Telegram:
    """Owns a Telethon client on its own event loop in a background thread."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.loop = None
        self.client = None
        self.entity = None
        self.ready = threading.Event()
        self.error = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        if not self.ready.wait(timeout=90):
            raise RuntimeError("Telegram client did not become ready in time")
        if self.error:
            raise self.error

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        try:
            loop.run_until_complete(self._connect())
        except Exception as exc:  # surfaced to start()
            self.error = exc
            self.ready.set()
            return
        self.ready.set()
        loop.run_forever()

    async def _connect(self):
        self.client = TelegramClient(
            str(SESSION_PATH),
            self.cfg["telegram_api_id"],
            self.cfg["telegram_api_hash"],
        )
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError(
                "Telegram session is not authorized. Re-run the setup to log in."
            )
        me = await self.client.get_me()
        log(f"Telegram: logged in as {me.first_name}")
        self.entity = await self._resolve_chat()
        log(f"Telegram: target chat resolved -> {self._describe(self.entity)}")

    async def _resolve_chat(self):
        raw = str(self.cfg["telegram_chat_id"]).strip()
        try:
            return await self.client.get_entity(int(raw))
        except (ValueError, TypeError):
            pass
        except Exception:
            pass
        # Fall back to scanning dialogs, which also warms the entity cache.
        async for dialog in self.client.iter_dialogs():
            if str(dialog.id) == raw or dialog.name == raw:
                return dialog.entity
        return await self.client.get_entity(raw)

    @staticmethod
    def _describe(entity):
        for attr in ("title", "username", "first_name"):
            value = getattr(entity, attr, None)
            if value:
                return value
        return str(getattr(entity, "id", entity))

    def send(self, text):
        future = asyncio.run_coroutine_threadsafe(self._send(text), self.loop)
        return future.result(timeout=60)

    async def _send(self, text):
        await self.client.send_message(self.entity, text, parse_mode="html")
        return True


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


def _strip_html(raw):
    import re

    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</p\s*>", "\n\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = "\n".join(line.strip() for line in raw.splitlines())
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def extract_body(msg):
    plain = ""
    rich = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_filename():
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if part.get_content_type() == "text/plain" and not plain:
                plain = text
            elif part.get_content_type() == "text/html" and not rich:
                rich = text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                rich = text
            else:
                plain = text

    body = plain.strip() or _strip_html(rich)
    if len(body) > BODY_LIMIT:
        body = body[:BODY_LIMIT].rstrip() + "\n\n[...truncated]"
    return body.strip()


def format_message(msg):
    sender = decode_mime_header(msg.get("From", "Unknown"))
    subject = decode_mime_header(msg.get("Subject", "(no subject)"))
    body = extract_body(msg)

    text = (
        f"<b>{html.escape(subject)}</b>\n"
        f"<i>from {html.escape(sender)}</i>\n\n"
        f"{html.escape(body)}"
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


def matches(sender_addr, watch):
    return any(w == sender_addr or w in sender_addr for w in watch)


def check_mailbox(mail, cfg, telegram):
    """Forward any unseen mail from a watched sender. Returns True if work was done."""
    watch = [s.lower().strip() for s in cfg["watch_senders"]]

    typ, data = mail.uid("search", None, "UNSEEN")
    if typ != "OK" or not data or not data[0]:
        return False

    did_work = False
    for uid in data[0].split():
        uid_str = uid.decode()
        if uid_str in seen_uids:
            continue

        typ, payload = mail.uid("fetch", uid, "(BODY.PEEK[])")
        if typ != "OK" or not payload or not isinstance(payload[0], tuple):
            continue

        msg = email.message_from_bytes(payload[0][1])
        sender_addr = email.utils.parseaddr(msg.get("From", ""))[1].lower()

        if not matches(sender_addr, watch):
            seen_uids.add(uid_str)
            continue

        with _state_lock:
            enabled = state["enabled"]

        if not enabled:
            # Paused: swallow it so resuming doesn't replay a backlog.
            seen_uids.add(uid_str)
            log(f"Paused - skipping mail from {sender_addr}")
            did_work = True
            continue

        subject = decode_mime_header(msg.get("Subject", ""))
        log(f"Forwarding from {sender_addr}: {subject}")
        try:
            telegram.send(format_message(msg))
        except Exception as exc:
            log(f"Telegram send failed ({exc}) - will retry on next pass")
            continue

        seen_uids.add(uid_str)
        with _state_lock:
            state["forwarded_count"] += 1
        log("Sent to Telegram")
        did_work = True

    if did_work:
        with _state_lock:
            save_state()
    return did_work


def idle_wait(mail, seconds):
    """Block until the server reports new mail, or until the timeout elapses."""
    tag = mail._new_tag().decode()
    mail.send(f"{tag} IDLE\r\n".encode())
    mail.readline()  # '+ idling'
    old_timeout = mail.sock.gettimeout()
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
        mail.sock.settimeout(old_timeout)
        try:
            mail.send(b"DONE\r\n")
            mail.readline()
        except Exception:
            pass


def watch_mailbox(cfg, telegram):
    use_idle = cfg.get("mode", "idle") != "poll"
    while True:
        mail = None
        try:
            log(f"Connecting to {cfg['imap_server']} ...")
            mail = connect_imap(cfg)
            has_idle = use_idle and b"IDLE" in (mail.capabilities and b" ".join(
                c.encode() if isinstance(c, str) else c for c in mail.capabilities))
            log("Connected. Mode: " + ("IDLE (instant)" if has_idle else "polling (15s)"))

            check_mailbox(mail, cfg, telegram)
            with _state_lock:
                state["last_check"] = now()
                save_state()

            while True:
                if has_idle:
                    idle_wait(mail, IDLE_SECONDS)
                else:
                    time.sleep(15)
                mail.noop()
                check_mailbox(mail, cfg, telegram)
                with _state_lock:
                    state["last_check"] = now()
                    save_state()

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
h1{font-size:15px;font-weight:600;letter-spacing:.01em;margin-bottom:18px;color:var(--muted)}
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
        with _state_lock:
            enabled = state["enabled"]
            count = state["forwarded_count"]
            last = state["last_check"] or "never"

        page = (PAGE
                .replace("var(--STATE)", "var(--on)" if enabled else "var(--off)")
                .replace("var(--BTN)", "var(--off)" if enabled else "var(--on)")
                .replace("__STATE__", "Running" if enabled else "Paused")
                .replace("__BTN__", "Pause" if enabled else "Resume")
                .replace("__COUNT__", str(count))
                .replace("__LAST__", last))
        body = page.encode()
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
        with _state_lock:
            state["enabled"] = not state["enabled"]
            save_state()
            log("Forwarder " + ("resumed" if state["enabled"] else "paused"))
        self.send_response(204)
        self.end_headers()


# --------------------------------------------------------------------------

def main():
    cfg = load_config()
    required = ["imap_server", "email", "password", "telegram_api_id",
                "telegram_api_hash", "telegram_chat_id", "watch_senders"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        log(f"ERROR: config.json is missing: {', '.join(missing)}")
        sys.exit(1)

    telegram = Telegram(cfg)
    telegram.start()

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

    watch_mailbox(cfg, telegram)


if __name__ == "__main__":
    main()
