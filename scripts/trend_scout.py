"""
trend_scout.py
--------------
Pulls the recent posts of the reference pages through the Instagram
Business Discovery API (public business/creator accounts only), ranks them
by engagement relative to follower count, reads the text off the top
image posts with Gemini vision, and writes:

  data/trends.json         -> the winning posts (idea source for the weekly batch)
  data/account_report.md   -> which of the 7 pages are actually worth studying

Env: IG_ACCESS_TOKEN, IG_BUSINESS_ID, GEMINI_API_KEY
"""

import os
import re
import sys
import json
import base64
import statistics
import requests
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gemini_util

ACCOUNTS = [
    "cashflowgodfather",
    "traditional.male",
    "cashflowlaws",
    "rarementalities",
    "theprimeadvice",
    "alphaadvice",
    "successskill",
]

HOSTS = ["https://graph.instagram.com", "https://graph.facebook.com"]
API_VER = "v21.0"

LOOKBACK_DAYS = 90      # only posts from the last N days count as "trending"
MIN_LIKES = 150         # ignore tiny outliers
MAX_PER_ACCOUNT = 3     # don't let one page dominate
TARGET_WINNERS = 14     # how many winning posts to keep
MAX_VISION_CALLS = 35   # hard cap on Gemini vision calls per run

TOKEN = os.environ.get("IG_ACCESS_TOKEN")
IG_ID = os.environ.get("IG_BUSINESS_ID")

FIELDS = (
    "business_discovery.username({u})"
    "{{username,followers_count,media_count,"
    "media.limit(50){{caption,like_count,comments_count,media_type,"
    "media_url,thumbnail_url,permalink,timestamp}}}}"
)

OCR_PROMPT = (
    "This is an Instagram post image from a self-improvement / money / masculinity page. "
    "Transcribe ALL the quote or text that is written on the image, exactly, keeping line "
    "breaks. Ignore watermarks, handles and logos. If there is no readable text, return "
    "an empty string. Return only the text."
)


def parse_ts(ts):
    return datetime.fromisoformat(re.sub(r"\+0000$", "+00:00", ts))


def fetch_account(username):
    errors = []
    for host in HOSTS:
        try:
            r = requests.get(
                f"{host}/{API_VER}/{IG_ID}",
                params={"fields": FIELDS.format(u=username), "access_token": TOKEN},
                timeout=45,
            )
        except Exception as e:
            errors.append(f"[{host}] {e}")
            continue
        if r.status_code == 200 and "business_discovery" in r.json():
            return r.json()["business_discovery"]
        errors.append(f"[{host}] HTTP {r.status_code} {r.text[:350]}")
    raise RuntimeError("\n      ".join(errors))


def analyse_account(bd):
    followers = bd.get("followers_count") or 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    posts = []
    for m in (bd.get("media") or {}).get("data", []):
        likes = m.get("like_count")
        if likes is None or not followers:   # hidden likes -> can't score
            continue
        try:
            when = parse_ts(m["timestamp"])
        except Exception:
            continue
        if when < cutoff:
            continue
        comments = m.get("comments_count") or 0
        posts.append({
            "account": bd["username"],
            "followers": followers,
            "likes": likes,
            "comments": comments,
            "rate": round((likes + 3 * comments) / followers * 100, 3),  # % of followers
            "type": m.get("media_type"),
            "image_url": m.get("media_url") if m.get("media_type") != "VIDEO" else m.get("thumbnail_url"),
            "caption": (m.get("caption") or "").strip(),
            "permalink": m.get("permalink"),
            "date": when.date().isoformat(),
        })

    summary = {
        "account": bd["username"],
        "followers": followers,
        "posts_scored": len(posts),
        "avg_likes": round(statistics.mean(p["likes"] for p in posts)) if posts else 0,
        "median_rate": round(statistics.median(p["rate"] for p in posts), 3) if posts else 0,
        "best_rate": max((p["rate"] for p in posts), default=0),
    }
    return summary, posts


def read_image_text(url):
    if not url:
        return ""
    img = requests.get(url, timeout=30)
    img.raise_for_status()
    mime = img.headers.get("content-type", "image/jpeg").split(";")[0]
    b64 = base64.b64encode(img.content).decode()
    return gemini_util.call(
        [{"text": OCR_PROMPT}, {"inline_data": {"mime_type": mime, "data": b64}}],
        temperature=0.0,
    ).strip()


def main():
    if not TOKEN or not IG_ID:
        sys.exit("IG_ACCESS_TOKEN / IG_BUSINESS_ID not set")
    os.makedirs("data", exist_ok=True)

    summaries, all_posts, failures = [], [], {}
    for user in ACCOUNTS:
        try:
            summary, posts = analyse_account(fetch_account(user))
            summaries.append(summary)
            all_posts.extend(posts)
            print(f"[ok] {user}: {summary['posts_scored']} posts scored, "
                  f"avg likes {summary['avg_likes']}, median rate {summary['median_rate']}%")
        except Exception as e:
            failures[user] = str(e)
            print(f"[FAIL] {user}: {e}")

    if not all_posts:
        sys.exit("No posts could be pulled for any account. See errors above.")

    # Rank every recent post by engagement rate, then read the text off the best ones.
    candidates = sorted(
        (p for p in all_posts if p["likes"] >= MIN_LIKES),
        key=lambda p: p["rate"], reverse=True,
    )

    winners, per_account, vision_calls = [], {}, 0
    for p in candidates:
        if len(winners) >= TARGET_WINNERS or vision_calls >= MAX_VISION_CALLS:
            break
        if per_account.get(p["account"], 0) >= MAX_PER_ACCOUNT:
            continue
        text = ""
        if p["image_url"]:
            vision_calls += 1
            try:
                text = read_image_text(p["image_url"])
            except Exception as e:
                print(f"[vision fail] {p['permalink']}: {e}")
        p["image_text"] = text
        # need real words to learn from (image text + caption)
        if len((text + " " + p["caption"]).split()) < 8:
            continue
        p.pop("image_url", None)
        winners.append(p)
        per_account[p["account"]] = per_account.get(p["account"], 0) + 1

    with open("data/trends.json", "w", encoding="utf-8") as f:
        json.dump({"generated": datetime.now(timezone.utc).isoformat(), "winners": winners}, f,
                  indent=2, ensure_ascii=False)

    # Human-readable account report
    summaries.sort(key=lambda s: s["median_rate"], reverse=True)
    lines = ["Reference pages ranked by median engagement (likes + 3x comments, as % of followers)\n"]
    for s in summaries:
        lines.append(f"- {s['account']}: {s['followers']:,} followers | avg {s['avg_likes']:,} likes | "
                     f"median {s['median_rate']}% | best post {s['best_rate']}%")
    for u, err in failures.items():
        lines.append(f"- {u}: COULD NOT PULL ({err[:120]})")
    lines.append(f"\nWinning posts kept as idea sources: {len(winners)}")
    with open("data/account_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))

    if not winners:
        sys.exit("Pulled data but found zero usable winning posts.")


if __name__ == "__main__":
    main()
