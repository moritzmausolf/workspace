#!/usr/bin/env python3
"""
Assemble the double-clickable macOS installer.

Reads the personal values from installer_config.json (gitignored) and embeds
them, together with the forwarder and the interactive setup helper, into a
single self-contained .command file.
"""

import json
import stat
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SETTINGS = BASE / "installer_config.json"
OUT = BASE / "Setup Email Forwarder.command"

REQUIRED = ["imap_server", "email", "watch_senders"]

DEFAULTS = {
    "imap_port": 993,
    "password": "",             # asked for during setup
    "telegram_bot_token": "",   # asked for during setup
    "telegram_chat_id": "",     # chosen during setup
    "code_pattern": "",         # when set, forward just the matched code
    "mode": "idle",
    "dashboard_port": 9876,
}


def check_no_delimiter(text, delimiter, name):
    for line in text.splitlines():
        if line.strip() == delimiter:
            raise SystemExit(f"{name} contains the heredoc delimiter {delimiter!r}")


def main():
    if not SETTINGS.exists():
        sys.exit(
            f"{SETTINGS.name} not found.\n"
            f"Copy installer_config.example.json to {SETTINGS.name} and fill it in."
        )

    settings = json.loads(SETTINGS.read_text())
    missing = [k for k in REQUIRED if not settings.get(k)]
    if missing:
        sys.exit(f"{SETTINGS.name} is missing: {', '.join(missing)}")

    config = {**DEFAULTS, **settings}
    config["password"] = ""
    config["telegram_bot_token"] = ""
    config["telegram_chat_id"] = ""

    template = (BASE / "setup_template.sh").read_text()
    forwarder = (BASE / "email_to_telegram.py").read_text()
    helper = (BASE / "setup_helper.py").read_text()
    menubar = (BASE / "menubar_toggle.swift").read_text()
    config_json = json.dumps(config, indent=2)

    check_no_delimiter(forwarder, "FORWARDER_EOF", "email_to_telegram.py")
    check_no_delimiter(helper, "HELPER_EOF", "setup_helper.py")
    check_no_delimiter(config_json, "CONFIG_EOF", "config")
    check_no_delimiter(menubar, "MENUBAR_EOF", "menubar_toggle.swift")

    script = (template
              .replace("__FORWARDER_PY__", forwarder.rstrip("\n"))
              .replace("__HELPER_PY__", helper.rstrip("\n"))
              .replace("__MENUBAR_SWIFT__", menubar.rstrip("\n"))
              .replace("__CONFIG_JSON__", config_json))

    OUT.write_text(script)
    OUT.chmod(OUT.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"wrote {OUT.name} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
