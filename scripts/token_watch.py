"""
token_watch.py
---------------
Runs daily. Writes token_issue.md ONLY if something needs your attention, and the
workflow turns that into a GitHub issue (GitHub emails you). Silent when all is well.

Checks:
  1. Instagram token: live validity test + days left, counted from the date you
     record in config/tokens.json (Instagram's own API does not reveal the expiry date).
  2. Media repo token (MEDIA_REPO_TOKEN): live write-access test + its expiry date, which
     GitHub reports in the 'github-authentication-token-expiration' response header.

Env: IG_USER_ID, IG_ACCESS_TOKEN, MEDIA_REPO, MEDIA_REPO_TOKEN
"""
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

import requests

import post_reel as pr  # explain_meta_error + GRAPH constants

CONFIG = Path("config/tokens.json")
ISSUE_FILE = Path("token_issue.md")

IG_FIX = ("Meta developer dashboard > your app > Instagram > API setup with Instagram login > "
          "**Generate token** for @rootedand.rich. Then GitHub > repo Settings > Secrets and "
          "variables > Actions > update **IG_ACCESS_TOKEN**. Finally edit "
          "`config/tokens.json` and set `ig_token_issued` to today's date.")
MEDIA_FIX = ("GitHub > your profile Settings > Developer settings > Fine-grained personal access "
             "tokens > regenerate the media token (repository: only `{repo}`, Contents: read and "
             "write). Then repo Settings > Secrets and variables > Actions > update "
             "**MEDIA_REPO_TOKEN**.")


def days_left_ig(issued, today, lifetime):
    return (date.fromisoformat(issued) - today).days + lifetime


def parse_expiry_header(value):
    """'2026-11-24 00:00:00 UTC' -> date, or None if absent/unreadable."""
    if not value:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", value.strip())
    return date.fromisoformat(m.group(1)) if m else None


def evaluate(cfg, today, ig_live_error, media_status, media_expiry, repo):
    """Pure decision logic. Returns a list of (title, detail) problems."""
    problems = []
    left = days_left_ig(cfg["ig_token_issued"], today, cfg.get("ig_token_lifetime_days", 60))
    if ig_live_error:
        problems.append(("Instagram token is NOT working", f"{ig_live_error}\n\n**Fix:** {IG_FIX}"))
    elif left <= cfg.get("warn_days_before", 10):
        when = f"expires in about {left} days" if left > 0 else "has passed its 60-day life"
        problems.append((f"Instagram token {when}",
                         f"Recorded as generated on {cfg['ig_token_issued']}. Posting stops "
                         f"when it expires.\n\n**Fix:** {IG_FIX}"))

    if media_status != "ok":
        problems.append(("Media repo token is NOT working",
                         f"{media_status}\n\n**Fix:** {MEDIA_FIX.format(repo=repo)}"))
    elif media_expiry is not None:
        mleft = (media_expiry - today).days
        if mleft <= cfg.get("media_warn_days_before", 14):
            problems.append((f"Media repo token expires in {max(mleft, 0)} days ({media_expiry})",
                             f"Posting stops when it expires.\n\n**Fix:** {MEDIA_FIX.format(repo=repo)}"))
    return problems


def check_instagram():
    token = os.environ["IG_ACCESS_TOKEN"].strip()
    resp = requests.get(f"{pr.GRAPH_HOST}/{pr.GRAPH_VERSION}/me",
                        params={"fields": "user_id,username", "access_token": token}, timeout=30)
    return None if resp.ok else pr.explain_meta_error(resp.text)


def check_media():
    repo = os.environ["MEDIA_REPO"].strip()
    token = os.environ["MEDIA_REPO_TOKEN"].strip()
    resp = requests.get(f"https://api.github.com/repos/{repo}",
                        headers={"Authorization": f"Bearer {token}",
                                 "Accept": "application/vnd.github+json"}, timeout=30)
    if resp.status_code in (401, 403, 404):
        return f"GitHub answered {resp.status_code}: the token has expired or lost access.", None
    resp.raise_for_status()
    if not (resp.json().get("permissions") or {}).get("push"):
        return "The token can see the repo but cannot write to it.", None
    return "ok", parse_expiry_header(resp.headers.get("github-authentication-token-expiration"))


def main():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    media_status, media_expiry = check_media()
    problems = evaluate(cfg, datetime.utcnow().date(), check_instagram(),
                        media_status, media_expiry, os.environ["MEDIA_REPO"].strip())

    left = days_left_ig(cfg["ig_token_issued"], datetime.utcnow().date(),
                        cfg.get("ig_token_lifetime_days", 60))
    print(f"Instagram token: about {left} days left (generated {cfg['ig_token_issued']}).")
    print(f"Media token: {media_status}; expires {media_expiry or 'unknown/never'}.")

    if not problems:
        print("All tokens fine. Nothing to report.")
        return
    lines = ["@kumargauravmh these need you before posting stops:", ""]
    for title, detail in problems:
        lines += [f"### {title}", detail, ""]
    ISSUE_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"::warning title=Token action needed::{'; '.join(t for t, _ in problems)}")


if __name__ == "__main__":
    main()
