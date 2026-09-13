"""
post_reel.py
Publishes a local .mp4 as an Instagram Reel via the Graph API.

Flow (Graph API requires a public URL, not a direct file upload, for video):
  1. Push the mp4 to a small PUBLIC repo (e.g. rootedandrich-media) so it's
     reachable at a raw.githubusercontent.com URL.
  2. POST /{ig-user-id}/media  with media_type=REELS + video_url -> creation_id
  3. Poll GET /{creation_id}?fields=status_code until FINISHED
  4. POST /{ig-user-id}/media_publish with creation_id -> live post

Env vars expected (add these as repo secrets, same pattern as your existing ones):
  IG_ACCESS_TOKEN       - existing Graph API token
  IG_BUSINESS_ID        - existing Instagram Business ID
  MEDIA_REPO            - e.g. "kumargauravmh/rootedandrich-media" (PUBLIC repo)
  MEDIA_REPO_TOKEN      - a GitHub token with push access to that repo
                           (can reuse GITHUB_TOKEN if the media repo lives in
                           the same org and Actions has cross-repo write set up;
                           otherwise use a separate PAT stored as a secret)
"""

import os
import subprocess
import sys
import time

import requests

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def push_to_media_repo(local_video_path: str, filename: str) -> str:
    """
    Pushes the video into the public media repo via a throwaway git clone,
    returns the raw.githubusercontent.com URL.
    """
    media_repo = os.environ["MEDIA_REPO"]        # "owner/repo"
    token = os.environ["MEDIA_REPO_TOKEN"]
    clone_dir = "media_repo_tmp"

    subprocess.run(["rm", "-rf", clone_dir], check=True)
    subprocess.run(
        ["git", "clone", f"https://x-access-token:{token}@github.com/{media_repo}.git", clone_dir],
        check=True, capture_output=True
    )
    dest = os.path.join(clone_dir, filename)
    subprocess.run(["cp", local_video_path, dest], check=True)

    subprocess.run(["git", "-C", clone_dir, "add", filename], check=True)
    subprocess.run(
        ["git", "-C", clone_dir, "-c", "user.email=bot@rootedandrich",
         "-c", "user.name=rootedandrich-bot", "commit", "-m", f"add {filename}"],
        check=True, capture_output=True
    )
    subprocess.run(["git", "-C", clone_dir, "push"], check=True, capture_output=True)

    branch = subprocess.run(
        ["git", "-C", clone_dir, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True
    ).stdout.strip()

    return f"https://raw.githubusercontent.com/{media_repo}/{branch}/{filename}"


def create_reel_container(video_url: str, caption: str) -> str:
    resp = requests.post(
        f"{GRAPH_BASE}/{os.environ['IG_BUSINESS_ID']}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": os.environ["IG_ACCESS_TOKEN"],
        },
    )
    resp.raise_for_status()
    return resp.json()["id"]


def wait_for_processing(creation_id: str, timeout_s: int = 300) -> None:
    start = time.time()
    while time.time() - start < timeout_s:
        resp = requests.get(
            f"{GRAPH_BASE}/{creation_id}",
            params={"fields": "status_code", "access_token": os.environ["IG_ACCESS_TOKEN"]},
        )
        resp.raise_for_status()
        status = resp.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Reel processing failed for {creation_id}")
        time.sleep(10)
    raise TimeoutError(f"Reel {creation_id} did not finish processing in {timeout_s}s")


def publish_reel(creation_id: str) -> dict:
    resp = requests.post(
        f"{GRAPH_BASE}/{os.environ['IG_BUSINESS_ID']}/media_publish",
        data={
            "creation_id": creation_id,
            "access_token": os.environ["IG_ACCESS_TOKEN"],
        },
    )
    resp.raise_for_status()
    return resp.json()


def post_reel(local_video_path: str, caption: str, filename: str) -> dict:
    video_url = push_to_media_repo(local_video_path, filename)
    print(f"Video hosted at: {video_url}")

    creation_id = create_reel_container(video_url, caption)
    print(f"Container created: {creation_id}")

    wait_for_processing(creation_id)
    print("Processing finished, publishing...")

    result = publish_reel(creation_id)
    print(f"Published: {result}")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python post_reel.py <video_path> <caption>")
        sys.exit(1)
    video_path, caption = sys.argv[1], sys.argv[2]
    fname = f"reel_{int(time.time())}.mp4"
    post_reel(video_path, caption, fname)
