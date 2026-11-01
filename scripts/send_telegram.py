"""
send_telegram.py
----------------
Sends the week's batch to your Telegram chat: for each day, the image (as a
file, so Telegram doesn't compress it) followed by the caption as plain text
you can long-press and copy.

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import os
import sys
import json
import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API = f"https://api.telegram.org/bot{TOKEN}"


def check(resp):
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram HTTP {resp.status_code}: {resp.text[:300]}")


def send_text(text):
    check(requests.post(f"{API}/sendMessage", data={"chat_id": CHAT_ID, "text": text[:4000]}, timeout=30))


def send_file(path):
    with open(path, "rb") as f:
        check(requests.post(f"{API}/sendDocument", data={"chat_id": CHAT_ID},
                            files={"document": f}, timeout=60))


def main():
    if not TOKEN or not CHAT_ID:
        sys.exit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")

    with open("weekly/latest.txt") as f:
        week_dir = f.read().strip()
    with open(f"{week_dir}/week.json", encoding="utf-8") as f:
        posts = json.load(f)

    intro = f"Your content for the week starting {posts[0]['date']} ({len(posts)} posts). One per day."
    if os.path.exists("data/account_report.md"):
        with open("data/account_report.md", encoding="utf-8") as f:
            intro += "\n\n" + f.read()
    send_text(intro)

    for p in posts:
        send_file(p["image"])
        send_text(f"DAY {p['day']} - {p['weekday']}\n\n{p['caption']}\n\n.\n.\n.\n{p['hashtags']}")
        ref = (f"REFERENCE for day {p['day']}: @{p['idea_from']}\n"
               f"{p.get('source_stats', '')}\n{p.get('idea_permalink') or ''}\n\n"
               f"Original text:\n{p.get('source_text') or '(none)'}")
        send_text(ref)

    print(f"Sent {len(posts)} posts to Telegram.")


if __name__ == "__main__":
    main()
