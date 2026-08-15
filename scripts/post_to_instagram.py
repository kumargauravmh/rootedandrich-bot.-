"""
post_to_instagram.py
---------------------
Publishes the image that generate_image.py just created (and that the
workflow just committed/pushed) to Instagram via the official Graph API.

Reads posts/latest.txt to know exactly which file was generated in this
same run (avoids any timing mismatch between the two scripts).

Required GitHub Actions secrets:
  IG_USER_ID       - your Instagram Business Account ID
  IG_ACCESS_TOKEN  - long-lived Graph API access token
  GITHUB_REPOSITORY - auto-provided by GitHub Actions (owner/repo)
"""

import os
import time
import requests

GRAPH_VERSION = "v21.0"
GRAPH_HOST = "https://graph.instagram.com"


def get_slug():
    with open("posts/latest.txt", "r") as f:
        return f.read().strip()


def build_image_url(slug):
    repo = os.environ["GITHUB_REPOSITORY"]
    return f"https://raw.githubusercontent.com/{repo}/main/posts/post_{slug}.png"


def build_story_image_url(slug):
    repo = os.environ["GITHUB_REPOSITORY"]
    return f"https://raw.githubusercontent.com/{repo}/main/posts/story_{slug}.png"


def read_caption(slug):
    with open(f"posts/caption_{slug}.txt", "r", encoding="utf-8") as f:
        return f.read().strip()


def create_media_container(ig_user_id, token, image_url, caption, media_type=None):
    url = f"{GRAPH_HOST}/{GRAPH_VERSION}/{ig_user_id}/media"
    data = {
        "image_url": image_url,
        "access_token": token,
    }
    if caption:
        data["caption"] = caption
    if media_type:
        data["media_type"] = media_type
    resp = requests.post(url, data=data)
    if not resp.ok:
        print(f"Meta API rejected the request. Full response: {resp.text}")
    resp.raise_for_status()
    return resp.json()["id"]


def wait_until_ready(container_id, token, timeout=60):
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
        time.sleep(5)
        waited += 5
    raise TimeoutError(f"Container {container_id} not ready after {timeout}s.")


def publish_container(ig_user_id, token, container_id):
    url = f"{GRAPH_HOST}/{GRAPH_VERSION}/{ig_user_id}/media_publish"
    resp = requests.post(url, data={
        "creation_id": container_id,
        "access_token": token,
    })
    if not resp.ok:
        print(f"Meta API rejected the publish request. Full response: {resp.text}")
    resp.raise_for_status()
    return resp.json()


def main():
    ig_user_id = os.environ["IG_USER_ID"].strip()
    token = os.environ["IG_ACCESS_TOKEN"].strip()

    print(f"IG_USER_ID length: {len(ig_user_id)}")
    print(f"IG_ACCESS_TOKEN length: {len(token)}")
    print(f"IG_ACCESS_TOKEN starts with 'IGAA': {token.startswith('IGAA')}")

    slug = get_slug()
    image_url = build_image_url(slug)
    caption = read_caption(slug)

    print(f"Posting image: {image_url}")

    container_id = create_media_container(ig_user_id, token, image_url, caption)
    print(f"Container created: {container_id}")

    wait_until_ready(container_id, token)
    print("Container ready, publishing...")

    result = publish_container(ig_user_id, token, container_id)
    print(f"Published to feed: {result}")

    # NOTE: Automatic Story posting has been turned off. Instagram's native
    # "Share to Story" look (rounded card, music, attribution) can only be
    # produced by a human tapping Share on a real post - the API can only
    # upload a plain full-screen image, which doesn't match that look.
    # If you want a post on your Story, the fastest way is to open the
    # feed post after it goes live and tap Share > Add to Story yourself -
    # two taps, and it gets Instagram's real polished treatment.


if __name__ == "__main__":
    main()
