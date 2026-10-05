#!/usr/bin/env python3
"""Interactive part of the installer: mailbox password, bot token, target chat."""

import getpass
import imaplib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from email_to_telegram import TelegramError, call_api  # noqa: E402

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
DEFAULTS_PATH = BASE / "config.defaults.json"


def ask(prompt):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\n  Cancelled.")


def ask_secret(prompt):
    try:
        return getpass.getpass(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\n  Cancelled.")


def save(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")


# ---------------------------------------------------------------- mailbox

def try_imap(cfg, password):
    try:
        mail = imaplib.IMAP4_SSL(cfg["imap_server"], cfg.get("imap_port", 993))
        mail.login(cfg["email"], password)
        mail.select("INBOX")
        mail.logout()
        return True, None
    except imaplib.IMAP4.error:
        return False, "password rejected"
    except Exception as exc:
        return False, str(exc)


def setup_mailbox(cfg):
    print("\n  --- Mailbox ---")
    if cfg.get("password"):
        ok, _ = try_imap(cfg, cfg["password"])
        if ok:
            print("  Already working.")
            return
        print("  The saved password no longer works.")

    print(f"\n  EMAIL password for {cfg['email']}")
    print("  (the mailbox password - typing is hidden)")
    for attempt in range(3):
        password = ask_secret("  Password: ")
        if not password:
            continue
        ok, why = try_imap(cfg, password)
        if ok:
            cfg["password"] = password
            save(cfg)
            print("  Connected.")
            return
        print(f"  Could not sign in: {why}\n")
    sys.exit("  Giving up on the mailbox.")


# ---------------------------------------------------------------- bot

def setup_bot(cfg):
    print("\n  --- Telegram bot ---")

    if cfg.get("telegram_bot_token"):
        try:
            bot = call_api(cfg["telegram_bot_token"], "getMe", {})
            print(f"  Using the saved bot @{bot['username']}.")
            return bot
        except TelegramError:
            print("  The saved bot token no longer works.")

    print()
    print("  If you do not have a bot yet:")
    print("    1. Open Telegram and message @BotFather")
    print("    2. Send  /newbot  and follow the two prompts")
    print("    3. It replies with a token like 123456789:AAE...")
    print()

    for attempt in range(3):
        token = ask("  Bot token: ")
        if not token:
            continue
        try:
            bot = call_api(token, "getMe", {})
        except TelegramError as exc:
            print(f"  That token was not accepted: {exc}\n")
            continue
        cfg["telegram_bot_token"] = token
        save(cfg)
        print(f"  Connected as @{bot['username']}.")
        return bot
    sys.exit("  Giving up on the bot token.")


def discover_chats(token):
    """Chats the bot has seen, newest first."""
    try:
        call_api(token, "deleteWebhook", {})
    except TelegramError:
        pass

    try:
        updates = call_api(token, "getUpdates", {"limit": 100, "timeout": 0})
    except TelegramError as exc:
        print(f"  Could not read updates: {exc}")
        return []

    chats = {}
    for update in updates:
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            chat = (update.get(key) or {}).get("chat")
            if not chat:
                continue
            name = (chat.get("title")
                    or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
                    or chat.get("username")
                    or str(chat["id"]))
            chats[chat["id"]] = (name, chat.get("type", "chat"))
    return list(chats.items())


def setup_chat(cfg, bot):
    print("\n  --- Target chat ---")
    username = bot["username"]
    print(f"\n  In Telegram, open the chat that should receive the emails, then:")
    print(f"    - if it is a group: add @{username} to it")
    print(f"    - if it is just you: open a chat with @{username}")
    print(f"    - then send  /start  in that chat")
    print()

    chats = []
    while not chats:
        ask("  Press return once you have sent /start there ")
        chats = discover_chats(cfg["telegram_bot_token"])
        if not chats:
            print("  Nothing seen yet. Make sure you sent /start in that chat.\n")
            if ask("  Type 'skip' to enter a chat ID by hand, or return to retry: ") == "skip":
                return manual_chat(cfg)

    print()
    for i, (chat_id, (name, kind)) in enumerate(chats, 1):
        print(f"   {i:>3}.  {name[:44]:<44} {kind}")
    print()

    while True:
        choice = ask(f"  Which one? (1-{len(chats)}): ")
        if choice.isdigit() and 1 <= int(choice) <= len(chats):
            chat_id, (name, _kind) = chats[int(choice) - 1]
            cfg["telegram_chat_id"] = str(chat_id)
            save(cfg)
            return name
        print("  Enter one of the numbers above.")


def manual_chat(cfg):
    chat_id = ask("  Chat ID: ")
    cfg["telegram_chat_id"] = chat_id
    save(cfg)
    return chat_id


def send_test(cfg, where):
    print()
    try:
        call_api(cfg["telegram_bot_token"], "sendMessage", {
            "chat_id": cfg["telegram_chat_id"],
            "text": ("<b>Email forwarder connected.</b>\n"
                     f"<i>Mail from {', '.join(cfg['watch_senders'])} will arrive here.</i>"),
            "parse_mode": "HTML",
        })
    except TelegramError as exc:
        sys.exit(f"  Could not post to that chat: {exc}")
    print(f"  Target chat: {where}")
    print("  A test message was just sent there - check it.")


def load_config():
    """Existing settings win; anything new in this build is filled in around them."""
    defaults = json.loads(DEFAULTS_PATH.read_text()) if DEFAULTS_PATH.exists() else {}
    existing = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}

    cfg = {**defaults, **existing}
    added = [k for k in defaults if k not in existing]
    if added:
        print(f"  Added new settings: {', '.join(added)}")
    if cfg != existing:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    return cfg


def main():
    cfg = load_config()
    setup_mailbox(cfg)
    bot = setup_bot(cfg)
    where = setup_chat(cfg, bot)
    send_test(cfg, where)


if __name__ == "__main__":
    main()
