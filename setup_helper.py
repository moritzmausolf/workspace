#!/usr/bin/env python3
"""Interactive part of the installer: mail password, Telegram sign-in, chat choice."""

import asyncio
import getpass
import imaplib
import json
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
SESSION_PATH = BASE / "telegram_session"


def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        sys.exit("\n  Cancelled.")


def ask_secret(prompt):
    try:
        return getpass.getpass(prompt).strip()
    except EOFError:
        sys.exit("\n  Cancelled.")


def save(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")


# ---------------------------------------------------------------- mailbox

def verify_mailbox(cfg):
    """Make sure the IMAP credentials work before we install anything."""
    print("\n  --- Mailbox ---")
    if cfg.get("password"):
        if try_imap(cfg, cfg["password"], quiet=True):
            print("  Credentials already working.")
            return
        print("  The saved password was rejected.")

    print(f"\n  Your EMAIL password for {cfg['email']}")
    print("  (this is the mailbox password, not Telegram - typing is hidden)")
    for attempt in range(3):
        password = ask_secret("  Password: ")
        if not password:
            continue
        if try_imap(cfg, password):
            cfg["password"] = password
            save(cfg)
            return
        if attempt < 2:
            print("  Try again.\n")
    sys.exit("  Could not sign in to the mailbox.")


def try_imap(cfg, password, quiet=False):
    try:
        mail = imaplib.IMAP4_SSL(cfg["imap_server"], cfg.get("imap_port", 993))
        mail.login(cfg["email"], password)
        mail.select("INBOX")
        mail.logout()
        if not quiet:
            print("  Mailbox: connected.")
        return True
    except imaplib.IMAP4.error:
        if not quiet:
            print("  Mailbox: wrong password.")
        return False
    except Exception as exc:
        if not quiet:
            print(f"  Mailbox: could not connect ({exc}).")
        return False


# ---------------------------------------------------------------- telegram

async def sign_in(client, phone):
    print(f"\n  Sending a login code to {phone} ...")
    sent = await client.send_code_request(phone)
    print("  Check the Telegram app for the code.\n")

    for attempt in range(3):
        code = ask("  Code: ")
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
            return
        except PhoneCodeInvalidError:
            if attempt < 2:
                print("  That code was not right.\n")
        except PhoneCodeExpiredError:
            sys.exit("  That code expired - run the installer again.")
        except SessionPasswordNeededError:
            print("\n  Your account uses two-step verification.")
            for pw_attempt in range(3):
                password = ask_secret("  Telegram password: ")
                try:
                    await client.sign_in(password=password)
                    return
                except Exception:
                    if pw_attempt < 2:
                        print("  Wrong password.\n")
            sys.exit("  Could not sign in to Telegram.")
    sys.exit("  Could not sign in to Telegram.")


async def pick_chat(client):
    print("\n  Loading your chats ...\n")
    dialogs = []
    async for dialog in client.iter_dialogs(limit=50):
        kind = "group" if dialog.is_group else "channel" if dialog.is_channel else "chat"
        dialogs.append((dialog.id, kind, dialog.name or "(no name)"))

    if not dialogs:
        sys.exit("  No chats found on this account.")

    for i, (_cid, kind, name) in enumerate(dialogs, 1):
        print(f"   {i:>3}.  {name[:46]:<46} {kind}")

    print()
    while True:
        choice = ask(f"  Which chat should receive the emails? (1-{len(dialogs)}): ")
        if choice.isdigit() and 1 <= int(choice) <= len(dialogs):
            return dialogs[int(choice) - 1]
        print("  Enter one of the numbers above.")


async def setup_telegram(cfg):
    print("\n  --- Telegram ---")
    client = TelegramClient(
        str(SESSION_PATH), cfg["telegram_api_id"], cfg["telegram_api_hash"]
    )
    await client.connect()

    if not await client.is_user_authorized():
        await sign_in(client, cfg["telegram_phone"])

    me = await client.get_me()
    print(f"  Signed in as {me.first_name}.")

    chat_id, _kind, name = await pick_chat(client)
    cfg["telegram_chat_id"] = str(chat_id)
    save(cfg)

    entity = await client.get_entity(chat_id)
    await client.send_message(
        entity,
        "<b>Email forwarder connected.</b>\n"
        f"<i>Mail from {', '.join(cfg['watch_senders'])} will arrive here.</i>",
        parse_mode="html",
    )
    await client.disconnect()
    print(f"\n  Target chat: {name}")
    print("  A test message was just sent there - have a look.")


def main():
    cfg = json.loads(CONFIG_PATH.read_text())
    verify_mailbox(cfg)
    asyncio.run(setup_telegram(cfg))


if __name__ == "__main__":
    main()
