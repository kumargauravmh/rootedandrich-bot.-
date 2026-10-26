"""
post_reel.py
-------------
Publishes the video that generate_reel.py just created (and the workflow
just committed/pushed) to Instagram as a Reel, via the Graph API.

Mirrors post_to_instagram.py's structure exactly — same host, same secrets,
same slug/caption file pattern — just swaps image_url -> video_url and
media_type=REELS, and adds one extra step: pushing the video to a small
PUBLIC repo first, since Instagram needs a public URL and your main repo
is private.

Required GitHub Actions secrets (reuses your existing two, adds two new):
  IG_USER_ID         - same one post_to_instagram.py already uses
  IG_ACCESS_TOKEN    - same one post_to_instagram.py already uses
  MEDIA_REPO         - NEW: e.g. "kumargauravmh/rootedandrich-media" (public)
  MEDIA_REPO_TOKEN   - NEW: fine-grained PAT, Contents: read & write, scoped
                        to only that repo
"""

import os
import subprocess
import sys
import time

import requests

GRAPH_VERSION = "v21.0"
GRAPH_HOST = "https://graph.instagram.com"


def explain_meta_error(raw):
    """One readable line from Meta's JSON error, plus the likely fix."""
    try:
        err = requests.models.complexjson.loads(raw).get("error", {})
    except Exception:
        return f"Unreadable response from Meta: {raw[:300]}"
    msg, code, sub = err.get("message", "?"), err.get("code"), err.get("error_subcode")
    hint = ""
    if code == 190 or "token" in msg.lower() or "session" in msg.lower():
        hint = (" FIX: the Instagram access token is expired or invalid. Generate a new "
                "token in the Meta developer dashboard (Instagram > API setup > Generate token) "
                "and replace the IG_ACCESS_TOKEN secret in GitHub > Settings > Secrets > Actions.")
    return f"Meta error {code}/{sub}: {msg}.{hint}"


def check_token():
    """Cheap pre-flight: is the Instagram token valid right now? Posts nothing."""
    ig_user_id = os.environ["IG_USER_ID"].strip()
    token = os.environ["IG_ACCESS_TOKEN"].strip()
    resp = requests.get(f"{GRAPH_HOST}/{GRAPH_VERSION}/me",
                        params={"fields": "user_id,username", "access_token": token}, timeout=30)
    if not resp.ok:
        print(f"::error title=Instagram token check failed::{explain_meta_error(resp.text)}")
        sys.exit(1)
    info = resp.json()
    print(f"Instagram token OK for @{info.get('username')} (user_id {info.get('user_id')}).")
    if str(info.get("user_id")) != ig_user_id and str(info.get("id")) != ig_user_id:
        print("::warning title=IG_USER_ID mismatch::The token belongs to a different account "
              "than the IG_USER_ID secret.")

    check_media_repo_token()


def check_media_repo_token():
    """The video is hosted in a public repo through a fine-grained GitHub token,
    which has its own expiry date. Verify it can still write to that repo."""
    media_repo = os.environ.get("MEDIA_REPO", "").strip()
    token = os.environ.get("MEDIA_REPO_TOKEN", "").strip()
    if not media_repo or not token:
        print("::error title=Media repo secrets missing::MEDIA_REPO or MEDIA_REPO_TOKEN is not set.")
        sys.exit(1)
    resp = requests.get(f"https://api.github.com/repos/{media_repo}",
                        headers={"Authorization": f"Bearer {token}",
                                 "Accept": "application/vnd.github+json"}, timeout=30)
    if resp.status_code in (401, 403, 404):
        print(f"::error title=Media repo token rejected::GitHub answered {resp.status_code} for "
              f"{media_repo}. The MEDIA_REPO_TOKEN has probably expired or lost access. FIX: "
              f"GitHub > Settings > Developer settings > Fine-grained tokens > regenerate it "
              f"(Contents: read and write, only on {media_repo}) and update the MEDIA_REPO_TOKEN "
              f"secret.")
        sys.exit(1)
    resp.raise_for_status()
    if not (resp.json().get("permissions") or {}).get("push"):
        print(f"::error title=Media repo token is read-only::The token can see {media_repo} but "
              f"cannot write to it. Give it Contents: read and write.")
        sys.exit(1)
    print(f"Media repo token OK: can push to {media_repo}.")


def get_slug():
    with open("posts/latest.txt", "r") as f:
        return f.read().strip()


def read_caption(slug):
    with open(f"posts/caption_{slug}.txt", "r", encoding="utf-8") as f:
        return f.read().strip()


def push_to_media_repo(local_video_path: str, filename: str) -> str:
    """
    Pushes the video into the public media repo via a throwaway clone,
    returns the raw.githubusercontent.com URL Instagram will fetch from.
    """
    media_repo = os.environ["MEDIA_REPO"]  # "owner/repo"
    token = os.environ["MEDIA_REPO_TOKEN"]
    clone_dir = "media_repo_tmp"

    def run_git(args, **kwargs):
        result = subprocess.run(args, capture_output=True, text=True, **kwargs)
        if result.returncode != 0:
            safe_args = [a.replace(token, "***TOKEN***") for a in args]
            print(f"Command failed: {safe_args}")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            raise RuntimeError(f"git command failed with exit code {result.returncode}")
        return result

    print(f"Cloning into media repo: {media_repo}")
    subprocess.run(["rm", "-rf", clone_dir], check=True)
    run_git(["git", "clone", f"https://x-access-token:{token}@github.com/{media_repo}.git", clone_dir])

    subprocess.run(["cp", local_video_path, os.path.join(clone_dir, filename)], check=True)

    # -f bypasses any .gitignore rule that might be silently excluding video
    # files (e.g. a default template's *.mp4 exclusion) — this repo should
    # always accept whatever we push to it.
    run_git(["git", "-C", clone_dir, "add", "-f", filename])

    status = run_git(["git", "-C", clone_dir, "status", "--porcelain"])
    if not status.stdout.strip():
        raise RuntimeError(
            f"Nothing staged after 'git add -f {filename}' — the file may not have "
            f"copied correctly, or something is preventing it from being tracked. "
            f"Check that {local_video_path} actually exists and has content."
        )

    run_git(["git", "-C", clone_dir, "-c", "user.email=rootedandrich-bot@users.noreply.github.com",
             "-c", "user.name=rootedandrich-bot", "commit", "-m", f"add {filename}"])
    run_git(["git", "-C", clone_dir, "push"])

    branch = run_git(["git", "-C", clone_dir, "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()

    return f"https://raw.githubusercontent.com/{media_repo}/{branch}/{filename}"


def create_media_container(ig_user_id, token, video_url, caption=None, media_type="REELS"):
    url = f"{GRAPH_HOST}/{GRAPH_VERSION}/{ig_user_id}/media"
    data = {
        "media_type": media_type,
        "video_url": video_url,
        "access_token": token,
    }
    if caption:
        data["caption"] = caption
    resp = requests.post(url, data=data)
    if not resp.ok:
        print(f"Meta API rejected the request. Full response: {resp.text}")
        print(f"::error title=Instagram rejected the reel::{explain_meta_error(resp.text)}")
    resp.raise_for_status()
    return resp.json()["id"]


def wait_until_ready(container_id, token, timeout=300):
    url = f"{GRAPH_HOST}/{GRAPH_VERSION}/{container_id}"
    waited = 0
    while waited < timeout:
        resp = requests.get(url, params={"fields": "status_code", "access_token": token})
        resp.raise_for_status()
        status = resp.json().get("status_code")
        if status == "FINISHED":
            return True
        if status == "ERROR":
            raise RuntimeError(f"Container {container_id} failed to process.")
        time.sleep(10)
        waited += 10
    raise TimeoutError(f"Container {container_id} not ready after {timeout}s.")


def publish_container(ig_user_id, token, container_id):
    url = f"{GRAPH_HOST}/{GRAPH_VERSION}/{ig_user_id}/media_publish"
    resp = requests.post(url, data={"creation_id": container_id, "access_token": token})
    if not resp.ok:
        print(f"Meta API rejected the publish request. Full response: {resp.text}")
        print(f"::error title=Instagram rejected the publish::{explain_meta_error(resp.text)}")
    resp.raise_for_status()
    return resp.json()


def main():
    ig_user_id = os.environ["IG_USER_ID"].strip()
    token = os.environ["IG_ACCESS_TOKEN"].strip()

    print(f"IG_USER_ID length: {len(ig_user_id)}")
    print(f"IG_ACCESS_TOKEN length: {len(token)}")
    print(f"IG_ACCESS_TOKEN starts with 'IGAA': {token.startswith('IGAA')}")

    slug = get_slug()
    caption = read_caption(slug)
    local_video_path = f"posts/reel_{slug}.mp4"
    media_filename = f"reel_{slug}.mp4"

    video_url = push_to_media_repo(local_video_path, media_filename)
    print(f"Video hosted at: {video_url}")

    # --- Publish the Reel to the feed (unchanged, this is what matters most) ---
    container_id = create_media_container(ig_user_id, token, video_url, caption, media_type="REELS")
    print(f"Reel container created: {container_id}")

    wait_until_ready(container_id, token)
    print("Reel container ready, publishing...")

    result = publish_container(ig_user_id, token, container_id)
    print(f"Published reel: {result}")
    # Stories are shared manually from the app (so the audio can be picked by hand).


if __name__ == "__main__":
    if "--check-token" in sys.argv:
        check_token()
    else:
        main()
