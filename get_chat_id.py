#!/usr/bin/env python3
"""List your recent Telegram chats and their IDs so you can find the right chat_id."""

import json, asyncio
from pathlib import Path
from telethon import TelegramClient

CONFIG_PATH = Path(__file__).parent / "config.json"
SESSION_PATH = Path(__file__).parent / "telegram_session"

async def main():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)

    client = TelegramClient(str(SESSION_PATH), cfg["telegram_api_id"], cfg["telegram_api_hash"])
    await client.start(phone=cfg.get("telegram_phone"))

    print("Your recent chats:\n")
    print(f"{'Chat ID':<20} {'Type':<10} {'Name'}")
    print("-" * 60)

    async for dialog in client.iter_dialogs(limit=30):
        chat_type = "Group" if dialog.is_group else "Channel" if dialog.is_channel else "User"
        print(f"{dialog.id:<20} {chat_type:<10} {dialog.name}")

    await client.disconnect()

asyncio.run(main())
