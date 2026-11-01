"""
telegram_chat_id.py
-------------------
One-time helper. After you create your bot with @BotFather and send it any
message (like "hi"), run:

    TELEGRAM_BOT_TOKEN=123:abc python scripts/telegram_chat_id.py

It prints your chat id. Save that as the TELEGRAM_CHAT_ID secret.
"""

import os
import sys
import requests

token = os.environ.get("TELEGRAM_BOT_TOKEN")
if not token:
    sys.exit("Set TELEGRAM_BOT_TOKEN first")

r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
r.raise_for_status()
results = r.json().get("result", [])
if not results:
    sys.exit("No messages found. Send your bot a message in Telegram first, then run this again.")

seen = set()
for u in results:
    chat = (u.get("message") or {}).get("chat") or {}
    if chat.get("id") and chat["id"] not in seen:
        seen.add(chat["id"])
        print(f"chat id: {chat['id']}  ({chat.get('first_name', '')} {chat.get('username', '')})")
