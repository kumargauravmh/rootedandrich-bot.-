"""
trend_scout.py
--------------
Pulls the recent posts of the reference pages through Apify's Instagram
scraper (Instagram's own API can't read other accounts with our token type), ranks them
by engagement relative to follower count, reads the text off the top
image posts with Gemini vision, and writes:

  data/trends.json         -> the winning posts (idea source for the weekly batch)
  data/account_report.md   -> which of the 7 pages are actually worth studying

Env: APIFY_TOKEN, GEMINI_API_KEY
"""

import os
import re
import sys
import json
import base64
import time
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

APIFY_ACTOR = "apify~instagram-scraper"
POSTS_PER_ACCOUNT = 15   # halves the Apify cost; newest posts come first
APIFY_WAIT_SECONDS = 600

LOOKBACK_DAYS = 90      # only posts from the last N days count as "trending"
MIN_LIKES = 100         # ignore tiny outliers
MAX_PER_ACCOUNT = 4     # don't let one page dominate
TARGET_WINNERS = 21     # how many winning posts to keep
MAX_VISION_CALLS = 45   # hard cap on Gemini vision calls per run

APIFY_TOKEN = os.environ.get("APIFY_TOKEN")

OCR_PROMPT = (
    "This is an Instagram post image from a self-improvement / money / masculinity page. "
    "Transcribe ALL the quote or text that is written on the image, exactly, keeping line "
    "breaks. Ignore watermarks, handles and logos. If there is no readable text, return "
    "an empty string. Return only the text."
)


def parse_ts(ts):
    return datetime.fromisoformat(re.sub(r"\+0000$", "+00:00", ts))


def apify_run(run_input):
    """Start the scraper, wait for it to finish, return the dataset items."""
    base = "https://api.apify.com/v2"
    r = requests.post(f"{base}/acts/{APIFY_ACTOR}/runs", params={"token": APIFY_TOKEN},
                      json=run_input, timeout=60)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Apify start failed HTTP {r.status_code}: {r.text[:400]}")
    run = r.json()["data"]
    deadline = time.time() + APIFY_WAIT_SECONDS
    while time.time() < deadline:
        time.sleep(8)
        st = requests.get(f"{base}/actor-runs/{run['id']}", params={"token": APIFY_TOKEN}, timeout=30).json()["data"]
        if st["status"] == "SUCCEEDED":
            items = requests.get(f"{base}/datasets/{st['defaultDatasetId']}/items",
                                 params={"token": APIFY_TOKEN, "clean": "true"}, timeout=120)
            items.raise_for_status()
            return items.json()
        if st["status"] in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Apify run {st['status']}: {st.get('statusMessage', '')}")
    raise RuntimeError("Apify run did not finish in time")


def parse_ts(ts):
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def fetch_all():
    urls = [f"https://www.instagram.com/{u}/" for u in ACCOUNTS]
    print("Apify: fetching follower counts...")
    details = apify_run({"directUrls": urls, "resultsType": "details", "resultsLimit": 1})
    followers = {}
    for d in details:
        if d.get("username") and d.get("followersCount"):
            followers[d["username"].lower()] = d["followersCount"]
    print(f"Apify: got followers for {len(followers)}/{len(ACCOUNTS)} accounts")

    print("Apify: fetching recent posts...")
    posts = apify_run({"directUrls": urls, "resultsType": "posts", "resultsLimit": POSTS_PER_ACCOUNT})
    print(f"Apify: got {len(posts)} posts")
    return followers, posts


def analyse(username, followers_n, raw_posts):
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    posts = []
    for m in raw_posts:
        likes = m.get("likesCount")
        if likes is None or likes < 0 or not followers_n:   # hidden likes -> can't score
            continue
        try:
            when = parse_ts(m["timestamp"])
        except Exception:
            continue
        if when < cutoff:
            continue
        comments = max(m.get("commentsCount") or 0, 0)
        posts.append({
            "account": username,
            "followers": followers_n,
            "likes": likes,
            "comments": comments,
            "rate": round((likes + 3 * comments) / followers_n * 100, 3),  # % of followers
            "type": m.get("type"),
            "image_url": m.get("displayUrl"),
            "caption": (m.get("caption") or "").strip(),
            "permalink": m.get("url"),
            "date": when.date().isoformat(),
        })

    summary = {
        "account": username,
        "followers": followers_n,
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
    if not APIFY_TOKEN:
        sys.exit("APIFY_TOKEN not set")
    os.makedirs("data", exist_ok=True)

    followers, raw = fetch_all()
    by_user = {}
    for m in raw:
        by_user.setdefault((m.get("ownerUsername") or "").lower(), []).append(m)

    summaries, all_posts, failures = [], [], {}
    for user in ACCOUNTS:
        try:
            if user.lower() not in followers:
                raise RuntimeError("no follower count returned")
            if user.lower() not in by_user:
                raise RuntimeError("no posts returned")
            summary, posts = analyse(user, followers[user.lower()], by_user[user.lower()])
            summaries.append(summary)
            all_posts.extend(posts)
            print(f"[ok] {user}: {summary['posts_scored']} posts scored, "
                  f"avg likes {summary['avg_likes']}, median rate {summary['median_rate']}%")
        except Exception as e:
            failures[user] = str(e)
            print(f"[FAIL] {user}: {e}")

    if not all_posts:
        sys.exit("No posts could be scored for any account. See errors above.")

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
