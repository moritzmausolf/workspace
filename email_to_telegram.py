#!/usr/bin/env python3
"""
Email-to-Telegram Forwarder
Monitors a Hostinger IMAP mailbox and forwards emails from specific senders
to a Telegram chat using your personal Telegram account (via Telethon).

Toggle on/off via the built-in web dashboard at http://localhost:9876

First run: you'll be prompted for your phone number and a login code.
After that, the session is saved and no further login is needed.
"""

import imaplib
import email
from email.header import decode_header
import time
import json
import threading
import signal
import sys
import os
import socket
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import asyncio

CONFIG_PATH = Path(__file__).parent / "config.json"
STATE_PATH = Path(__file__).parent / ".forwarder_state.json"
SESSION_PATH = Path(__file__).parent / "telegram_session"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config():
    if not CONFIG_PATH.exists():
        print(f"ERROR: {CONFIG_PATH} not found. Copy config.example.json and fill in your details.")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)

# ---------------------------------------------------------------------------
# State (on/off toggle persisted to disk)
# ---------------------------------------------------------------------------

def load_state():
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"enabled": True, "last_check": None, "forwarded_count": 0}

def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)

state = load_state()
state_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Telegram (Telethon — sends as YOUR account)
# ---------------------------------------------------------------------------

telegram_client = None
telegram_loop = None

async def init_telegram(cfg):
    from telethon import TelegramClient
    global telegram_client, telegram_loop

    session_file = str(SESSION_PATH)
    client = TelegramClient(
        session_file,
        cfg["telegram_api_id"],
        cfg["telegram_api_hash"],
    )
    await client.start(phone=cfg.get("telegram_phone"))
    me = await client.get_me()
    print(f"[{now()}] Logged into Telegram as {me.first_name} ({me.phone})")
    telegram_client = client
    telegram_loop = asyncio.get_event_loop()
    return client

async def send_telegram_message(chat_id, text):
    global telegram_client
    if not telegram_client:
        return None
    try:
        entity = await telegram_client.get_entity(int(chat_id))
        result = await telegram_client.send_message(entity, text, parse_mode="html")
        return result
    except Exception as e:
        print(f"[{now()}] Telegram send error: {e}")
        return None

def send_telegram(chat_id, text):
    if telegram_loop and telegram_client:
        future = asyncio.run_coroutine_threadsafe(
            send_telegram_message(chat_id, text),
            telegram_loop,
        )
        try:
            return future.result(timeout=15)
        except Exception as e:
            print(f"[{now()}] Telegram send error: {e}")
            return None
    return None

# ---------------------------------------------------------------------------
# Email parsing
# ---------------------------------------------------------------------------

def decode_mime_header(raw):
    parts = decode_header(raw or "")
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)

def extract_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
                    break
            elif ct == "text/html" and not body:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
    if len(body) > 3500:
        body = body[:3500] + "\n\n... [truncated]"
    return body.strip()

def format_for_telegram(msg):
    sender = decode_mime_header(msg.get("From", "Unknown"))
    subject = decode_mime_header(msg.get("Subject", "(no subject)"))
    date = msg.get("Date", "")
    body = extract_body(msg)

    import html
    text = (
        f"\U0001f4e7 <b>New Email</b>\n"
        f"<b>From:</b> {html.escape(sender)}\n"
        f"<b>Subject:</b> {html.escape(subject)}\n"
        f"<b>Date:</b> {html.escape(date)}\n"
        f"\n{html.escape(body)}"
    )
    return text

# ---------------------------------------------------------------------------
# IMAP watcher
# ---------------------------------------------------------------------------

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def connect_imap(cfg):
    mail = imaplib.IMAP4_SSL(cfg["imap_server"], cfg.get("imap_port", 993))
    mail.login(cfg["email"], cfg["password"])
    mail.select("INBOX")
    return mail

def check_new_emails(mail, cfg, seen_uids):
    global state
    with state_lock:
        if not state["enabled"]:
            return seen_uids

    senders = [s.lower() for s in cfg["watch_senders"]]
    _, data = mail.uid("search", None, "UNSEEN")
    uids = data[0].split()

    for uid in uids:
        uid_str = uid.decode()
        if uid_str in seen_uids:
            continue

        _, msg_data = mail.uid("fetch", uid, "(RFC822)")
        if not msg_data or not msg_data[0]:
            continue

        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        sender_addr = email.utils.parseaddr(msg.get("From", ""))[1].lower()

        if sender_addr in senders or any(s in sender_addr for s in senders):
            subject = decode_mime_header(msg.get("Subject", ""))
            print(f"[{now()}] Forwarding email from {sender_addr}: {subject}")
            text = format_for_telegram(msg)
            result = send_telegram(cfg["telegram_chat_id"], text)
            if result:
                print(f"[{now()}] Sent to Telegram")
                with state_lock:
                    state["forwarded_count"] = state.get("forwarded_count", 0) + 1
                    state["last_check"] = now()
                    save_state(state)
            else:
                print(f"[{now()}] Telegram send failed")

        seen_uids.add(uid_str)

    return seen_uids

def imap_idle_loop(cfg):
    seen_uids = set()
    while True:
        try:
            print(f"[{now()}] Connecting to {cfg['imap_server']}...")
            mail = connect_imap(cfg)
            print(f"[{now()}] Connected. Starting IDLE watch...")

            seen_uids = check_new_emails(mail, cfg, seen_uids)

            while True:
                with state_lock:
                    state["last_check"] = now()
                    save_state(state)

                try:
                    tag = mail._new_tag().decode()
                    mail.send(f"{tag} IDLE\r\n".encode())
                    resp = mail.readline()

                    mail.sock.settimeout(240)
                    try:
                        while True:
                            line = mail.readline().decode(errors="replace")
                            if "EXISTS" in line or "RECENT" in line:
                                break
                            if line.startswith(tag):
                                break
                    except (socket.timeout, OSError):
                        pass

                    mail.send(b"DONE\r\n")
                    try:
                        mail.readline()
                    except Exception:
                        pass

                    mail.noop()
                    seen_uids = check_new_emails(mail, cfg, seen_uids)

                except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError) as e:
                    print(f"[{now()}] IDLE error: {e}. Reconnecting in 5s...")
                    time.sleep(5)
                    break

        except Exception as e:
            print(f"[{now()}] Connection error: {e}. Retrying in 10s...")
            time.sleep(10)

def polling_loop(cfg):
    seen_uids = set()
    while True:
        try:
            mail = connect_imap(cfg)
            print(f"[{now()}] Connected (polling mode). Checking every 15s...")
            while True:
                with state_lock:
                    if state["enabled"]:
                        seen_uids = check_new_emails(mail, cfg, seen_uids)
                    state["last_check"] = now()
                    save_state(state)
                time.sleep(15)
                mail.noop()
        except Exception as e:
            print(f"[{now()}] Error: {e}. Reconnecting in 10s...")
            time.sleep(10)

# ---------------------------------------------------------------------------
# Web dashboard (toggle on/off)
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Email Forwarder</title>
<style>
  :root {
    --bg: #0f0f0f; --fg: #e8e8e8; --card: #1a1a1a; --accent: #4ade80;
    --accent-off: #f87171; --border: #333;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg); color: var(--fg);
    display: flex; justify-content: center; align-items: center;
    min-height: 100vh; padding: 16px;
  }
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 16px; padding: 32px; max-width: 380px; width: 100%;
    text-align: center;
  }
  h1 { font-size: 20px; margin-bottom: 8px; }
  .status { font-size: 14px; color: #888; margin-bottom: 24px; }
  .toggle-btn {
    width: 100%; padding: 16px; border: none; border-radius: 12px;
    font-size: 18px; font-weight: 600; cursor: pointer;
    transition: all 0.2s;
  }
  .toggle-btn.on {
    background: var(--accent-off); color: #1a1a1a;
  }
  .toggle-btn.off {
    background: var(--accent); color: #1a1a1a;
  }
  .toggle-btn:hover { opacity: 0.85; transform: scale(0.98); }
  .indicator {
    display: inline-block; width: 12px; height: 12px; border-radius: 50%;
    margin-right: 8px; vertical-align: middle;
  }
  .indicator.on { background: var(--accent); box-shadow: 0 0 8px var(--accent); }
  .indicator.off { background: var(--accent-off); box-shadow: 0 0 8px var(--accent-off); }
  .stats { margin-top: 20px; font-size: 13px; color: #666; }
</style>
</head>
<body>
<div class="card">
  <h1>Email Forwarder</h1>
  <p class="status">
    <span class="indicator {{STATE_CLASS}}"></span>
    {{STATE_TEXT}}
  </p>
  <button class="toggle-btn {{BTN_CLASS}}" onclick="toggle()">
    {{BTN_TEXT}}
  </button>
  <div class="stats">
    Emails forwarded: {{COUNT}}<br>
    Last check: {{LAST_CHECK}}
  </div>
</div>
<script>
async function toggle() {
  const res = await fetch('/toggle', { method: 'POST' });
  if (res.ok) location.reload();
}
</script>
</body>
</html>"""

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        with state_lock:
            enabled = state["enabled"]
            count = state.get("forwarded_count", 0)
            last = state.get("last_check", "never")

        page = DASHBOARD_HTML
        page = page.replace("{{STATE_CLASS}}", "on" if enabled else "off")
        page = page.replace("{{STATE_TEXT}}", "Running" if enabled else "Paused")
        page = page.replace("{{BTN_CLASS}}", "on" if enabled else "off")
        page = page.replace("{{BTN_TEXT}}", "Pause Forwarder" if enabled else "Start Forwarder")
        page = page.replace("{{COUNT}}", str(count))
        page = page.replace("{{LAST_CHECK}}", last)

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(page.encode())

    def do_POST(self):
        if self.path == "/toggle":
            with state_lock:
                state["enabled"] = not state["enabled"]
                save_state(state)
                status = "enabled" if state["enabled"] else "paused"
                print(f"[{now()}] Forwarder {status} via dashboard")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cfg = load_config()

    required = ["imap_server", "email", "password", "telegram_api_id", "telegram_api_hash", "telegram_chat_id", "watch_senders"]
    for key in required:
        if key not in cfg or not cfg[key]:
            print(f"ERROR: '{key}' is missing or empty in config.json")
            sys.exit(1)

    port = cfg.get("dashboard_port", 9876)

    # Start Telegram client in its own thread with its own event loop
    def run_telegram():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(init_telegram(cfg))
        global telegram_loop
        telegram_loop = loop
        loop.run_forever()

    tg_thread = threading.Thread(target=run_telegram, daemon=True)
    tg_thread.start()
    time.sleep(3)  # wait for Telegram login

    # Start web dashboard
    server = HTTPServer(("127.0.0.1", port), DashboardHandler)
    dash_thread = threading.Thread(target=server.serve_forever, daemon=True)
    dash_thread.start()
    print(f"[{now()}] Dashboard running at http://localhost:{port}")
    print(f"[{now()}] Watching for emails from: {', '.join(cfg['watch_senders'])}")

    def shutdown(sig, frame):
        print(f"\n[{now()}] Shutting down...")
        server.shutdown()
        if telegram_client:
            asyncio.run_coroutine_threadsafe(telegram_client.disconnect(), telegram_loop)
        sys.exit(0)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    mode = cfg.get("mode", "idle")
    if mode == "poll":
        polling_loop(cfg)
    else:
        try:
            imap_idle_loop(cfg)
        except Exception as e:
            print(f"[{now()}] IDLE failed ({e}), falling back to polling...")
            polling_loop(cfg)

if __name__ == "__main__":
    if "--login-only" in sys.argv:
        cfg = load_config()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(init_telegram(cfg))
        print("Telegram login successful! Session saved.")
        loop.run_until_complete(telegram_client.disconnect())
    else:
        main()
