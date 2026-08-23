"""
Rooted and Rich — Instagram Analytics Puller
Fetches account-level and per-post insights via the Instagram Graph API
and saves them to analytics_log.json (appending each run's snapshot).

REQUIRED ENV VARS (set these as GitHub Secrets, same place as your posting token):
    INSTAGRAM_ACCESS_TOKEN      -> the long-lived token you just updated
    INSTAGRAM_BUSINESS_ID       -> your Instagram Business Account numeric ID

NOTE ON VARIABLE NAMES: if your existing posting script already uses different
secret names (e.g. IG_TOKEN, IG_USER_ID), either rename the secrets to match
below, or change the os.environ.get(...) keys here to match your existing ones.
Keep them consistent across both scripts.
"""

import os
import json
import requests
from datetime import datetime, timezone

ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
IG_BUSINESS_ID = os.environ.get("INSTAGRAM_BUSINESS_ID")
GRAPH_API_VERSION = "v21.0"  # bump this periodically — Meta deprecates old versions
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
LOG_FILE = "analytics_log.json"

# Metrics can vary by media type (IMAGE vs VIDEO vs CAROUSEL vs REELS) and by
# API version — Meta changes these periodically. This list is a reasonable
# starting point; if a metric fails, we skip it instead of failing the whole run.
CANDIDATE_MEDIA_METRICS = ["reach", "saved", "likes", "comments", "shares", "total_interactions"]
ACCOUNT_METRICS = ["reach", "profile_views", "accounts_engaged"]


def _get(url, params):
    params = {**params, "access_token": ACCESS_TOKEN}
    resp = requests.get(url, params=params, timeout=30)
    data = resp.json()
    if "error" in data:
        print(f"  [warn] {url} -> {data['error'].get('message')}")
        return None
    return data


def get_recent_media(limit=30):
    url = f"{BASE_URL}/{IG_BUSINESS_ID}/media"
    params = {"fields": "id,caption,media_type,timestamp,permalink", "limit": limit}
    data = _get(url, params)
    return data.get("data", []) if data else []


def get_media_insights(media_id, media_type):
    url = f"{BASE_URL}/{media_id}/insights"
    results = {}
    for metric in CANDIDATE_MEDIA_METRICS:
        data = _get(url, {"metric": metric})
        if data and data.get("data"):
            values = data["data"][0].get("values", [])
            if values:
                results[metric] = values[0].get("value")
    return results


def get_account_insights():
    url = f"{BASE_URL}/{IG_BUSINESS_ID}/insights"
    results = {}
    for metric in ACCOUNT_METRICS:
        data = _get(url, {"metric": metric, "period": "day"})
        if data and data.get("data"):
            values = data["data"][0].get("values", [])
            if values:
                results[metric] = values[-1].get("value")
    return results


def main():
    if not ACCESS_TOKEN or not IG_BUSINESS_ID:
        raise SystemExit(
            "Missing INSTAGRAM_ACCESS_TOKEN or INSTAGRAM_BUSINESS_ID env vars. "
            "Check your GitHub Secrets names match this script."
        )

    print("Fetching account-level insights...")
    account_snapshot = get_account_insights()

    print("Fetching recent posts...")
    media_items = get_recent_media()

    print(f"Fetching insights for {len(media_items)} posts...")
    post_snapshots = []
    for item in media_items:
        insights = get_media_insights(item["id"], item.get("media_type"))
        post_snapshots.append({
            "id": item["id"],
            "timestamp": item.get("timestamp"),
            "media_type": item.get("media_type"),
            "caption_preview": (item.get("caption") or "")[:80],
            "permalink": item.get("permalink"),
            "insights": insights,
        })

    snapshot = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "account": account_snapshot,
        "posts": post_snapshots,
    }

    # Append to existing log rather than overwrite
    log = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            try:
                log = json.load(f)
            except json.JSONDecodeError:
                log = []
    log.append(snapshot)

    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)

    print(f"Done. Logged {len(post_snapshots)} posts to {LOG_FILE}")


if __name__ == "__main__":
    main()
