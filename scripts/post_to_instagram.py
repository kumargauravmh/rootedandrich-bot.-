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


def get_slug():
    with open("posts/latest.txt", "r") as f:
        return f.read().strip()


def build_image_url(slug):
    repo = os.environ["GITHUB_REPOSITORY"]
    return f"https://raw.githubusercontent.com/{repo}/main/posts/post_{slug}.png"


def read_caption(slug):
    # generate_image.py already appends this post's tailored hashtags
    # directly into the caption file, so we just read it as-is.
    with open(f"posts/caption_{slug}.txt", "r", encoding="utf-8") as f:
        return f.read().strip()


def create_media_container(ig_user_id, token, image_url, caption):
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{ig_user_id}/media"
    resp = requests.post(url, data={
        "image_url": image_url,
        "caption": caption,
        "access_token": token,
    })
    resp.raise_for_status()
    return resp.json()["id"]


def wait_until_ready(container_id, token, timeout=60):
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{container_id}"
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
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{ig_user_id}/media_publish"
    resp = requests.post(url, data={
        "creation_id": container_id,
        "access_token": token,
    })
    resp.raise_for_status()
    return resp.json()


def main():
    ig_user_id = os.environ["IG_USER_ID"]
    token = os.environ["IG_ACCESS_TOKEN"]

    slug = get_slug()
    image_url = build_image_url(slug)
    caption = read_caption(slug)

    print(f"Posting image: {image_url}")

    container_id = create_media_container(ig_user_id, token, image_url, caption)
    print(f"Container created: {container_id}")

    wait_until_ready(container_id, token)
    print("Container ready, publishing...")

    result = publish_container(ig_user_id, token, container_id)
    print(f"Published: {result}")


if __name__ == "__main__":
    main()
