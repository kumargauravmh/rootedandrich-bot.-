"""
post_carousel.py
-----------------
Publishes what carousel_reel.py just built.

  posts/latest_format.txt == "carousel"  -> swipeable image post (this file)
  posts/latest_format.txt == "reel"      -> hands over to post_reel.py (video)

Carousel flow on the Instagram Graph API (same host/secrets as post_reel.py):
  1. push the slide JPEGs to the public media repo (Instagram needs public URLs)
  2. one child container per slide      (is_carousel_item=true, image_url)
  3. one parent container               (media_type=CAROUSEL, children=id,id,...)
  4. media_publish

Limits worth knowing: JPEG only, 2-10 slides, every slide cropped to the first
slide's shape (all ours are 1080x1350, 4:5), caption up to 2,200 characters.

Secrets: IG_USER_ID, IG_ACCESS_TOKEN, MEDIA_REPO, MEDIA_REPO_TOKEN
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import requests

import post_reel as pr  # same folder: shared constants and helpers

POSTS_DIR = Path("posts")
MAX_SLIDES = 10
MAX_CAPTION = 2200


def run_git(args, token):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        safe = [a.replace(token, "***TOKEN***") for a in args]
        print(f"Command failed: {safe}\nstdout: {result.stdout}\nstderr: {result.stderr}")
        raise RuntimeError(f"git command failed with exit code {result.returncode}")
    return result


def push_slides_to_media_repo(slide_paths, slug):
    """One commit, one folder per post. Returns the public raw URLs in slide order."""
    media_repo = os.environ["MEDIA_REPO"].strip()
    token = os.environ["MEDIA_REPO_TOKEN"].strip()
    clone_dir = "media_repo_tmp"
    folder = f"carousel_{slug}"

    subprocess.run(["rm", "-rf", clone_dir], check=True)
    run_git(["git", "clone", "--depth", "1",
             f"https://x-access-token:{token}@github.com/{media_repo}.git", clone_dir], token)
    os.makedirs(os.path.join(clone_dir, folder), exist_ok=True)

    names = []
    for p in slide_paths:
        subprocess.run(["cp", str(p), os.path.join(clone_dir, folder, p.name)], check=True)
        names.append(f"{folder}/{p.name}")

    # -f: never let a stray .gitignore silently skip an image
    run_git(["git", "-C", clone_dir, "add", "-f", folder], token)
    status = run_git(["git", "-C", clone_dir, "status", "--porcelain"], token)
    if not status.stdout.strip():
        raise RuntimeError(f"Nothing staged for {folder}; the slide images did not copy.")
    run_git(["git", "-C", clone_dir, "-c", "user.email=rootedandrich-bot@users.noreply.github.com",
             "-c", "user.name=rootedandrich-bot", "commit", "-m", f"add {folder}"], token)
    run_git(["git", "-C", clone_dir, "push"], token)
    branch = run_git(["git", "-C", clone_dir, "rev-parse", "--abbrev-ref", "HEAD"],
                     token).stdout.strip()
    return [f"https://raw.githubusercontent.com/{media_repo}/{branch}/{n}" for n in names]


def wait_until_public(url, tries=12, delay=5):
    """raw.githubusercontent.com can lag a few seconds behind a push."""
    for _ in range(tries):
        try:
            if requests.head(url, timeout=15).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(delay)
    raise TimeoutError(f"Slide image never became publicly reachable: {url}")


def _post(url, data, what):
    resp = requests.post(url, data=data)
    if not resp.ok:
        print(f"Meta API rejected {what}. Full response: {resp.text}")
        print(f"::error title=Instagram rejected {what}::{pr.explain_meta_error(resp.text)}")
    resp.raise_for_status()
    return resp.json()


def create_child_container(ig_user_id, token, image_url):
    url = f"{pr.GRAPH_HOST}/{pr.GRAPH_VERSION}/{ig_user_id}/media"
    return _post(url, {"image_url": image_url, "is_carousel_item": "true",
                       "access_token": token}, "a slide")["id"]


def create_carousel_container(ig_user_id, token, children, caption):
    url = f"{pr.GRAPH_HOST}/{pr.GRAPH_VERSION}/{ig_user_id}/media"
    return _post(url, {"media_type": "CAROUSEL", "children": ",".join(children),
                       "caption": caption, "access_token": token}, "the carousel")["id"]


def publish_carousel(slide_paths, caption, slug):
    ig_user_id = os.environ["IG_USER_ID"].strip()
    token = os.environ["IG_ACCESS_TOKEN"].strip()

    if not 2 <= len(slide_paths) <= MAX_SLIDES:
        raise ValueError(f"A carousel needs 2-{MAX_SLIDES} slides, got {len(slide_paths)}")
    if len(caption) > MAX_CAPTION:
        raise ValueError(f"Caption is {len(caption)} characters; Instagram's limit is {MAX_CAPTION}")
    for p in slide_paths:
        if p.suffix.lower() not in (".jpg", ".jpeg"):
            raise ValueError(f"{p.name}: Instagram only accepts JPEG images")

    urls = push_slides_to_media_repo(slide_paths, slug)
    print(f"Hosted {len(urls)} slides, first: {urls[0]}")
    for u in urls:
        wait_until_public(u)

    children = []
    for i, u in enumerate(urls, 1):
        cid = create_child_container(ig_user_id, token, u)
        pr.wait_until_ready(cid, token)
        children.append(cid)
        print(f"Slide {i}/{len(urls)} ready: {cid}")

    parent = create_carousel_container(ig_user_id, token, children, caption)
    print(f"Carousel container created: {parent}")
    pr.wait_until_ready(parent, token)
    print("Carousel ready, publishing...")
    result = pr.publish_container(ig_user_id, token, parent)
    print(f"Published carousel: {result}")
    return result


def main():
    fmt_file = POSTS_DIR / "latest_format.txt"
    fmt = fmt_file.read_text().strip() if fmt_file.exists() else "reel"
    if fmt == "reel":
        print("Latest build is a reel; handing over to post_reel.py")
        return pr.main()

    slug = pr.get_slug()
    caption = pr.read_caption(slug)
    slides = sorted((POSTS_DIR / f"carousel_{slug}").glob("slide_*.jpg"))
    publish_carousel(slides, caption, slug)
    # Stories are shared manually from the app (so the audio can be picked by hand).


if __name__ == "__main__":
    main()
