"""
carousel_reel.py
-----------------
Weekly pipeline step: takes the next unpublished carousel from content/queue/ and
renders it. POST_FORMAT=carousel (default) makes one 1080x1350 JPEG per slide for a
swipeable feed post; POST_FORMAT=reel makes a silent 1080x1920 video instead.

Writes the same files the old pipeline wrote, so post_reel.py keeps working:
  posts/reel_<slug>.mp4
  posts/caption_<slug>.txt
  posts/latest.txt
plus:
  posts/latest_item.txt   (the queue item id, used by --mark-published)

Usage:
  python scripts/carousel_reel.py                  # build the next queued reel
  python scripts/carousel_reel.py --mark-published # call AFTER a successful post

No fallback content: an empty queue fails the run loudly (you get a GitHub
failure email) instead of reposting something old.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

QUEUE_DIR = Path("content/queue")
STATE_FILE = Path("content/state.json")
POSTS_DIR = Path("posts")
BUILD_DIR = Path("reel_build")

# --- Slide look (matches @rootedand.rich: black, left-aligned, regular body) ---
SLIDE_W, SLIDE_H = 1080, 1350
REEL_W, REEL_H = 1080, 1920
BLACK = "#000000"
WHITE = "#F0F0EC"
MUTED = "#6B6B65"
GOLD = "#C9A84C"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MARGIN_X = 90
TOP = 150
BOTTOM = SLIDE_H - 150
MAX_W = SLIDE_W - 2 * MARGIN_X

# --- Timing: seconds on screen = base + words / reading speed, clamped ---
BASE_SECONDS = 2.0
WORDS_PER_SECOND = 4.5
MIN_SECONDS = 4.0
MAX_SECONDS = 9.0
FPS = 30


def signal_github_output(generated: bool):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"generated={'true' if generated else 'false'}\n")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"published": []}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def next_item():
    """First queue file (alphabetical) whose id isn't in the published list."""
    state = load_state()
    for path in sorted(QUEUE_DIR.glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        if item["id"] not in state["published"]:
            return item
    return None


def validate(item):
    for key in ("id", "caption", "hashtags", "slides"):
        if not item.get(key):
            raise ValueError(f"queue item is missing '{key}'")
    if not 2 <= len(item["slides"]) <= 10:
        raise ValueError(f"carousel needs 2-10 slides, got {len(item['slides'])}")
    for i, s in enumerate(item["slides"], 1):
        if not s.get("heading") or not s.get("body"):
            raise ValueError(f"slide {i} needs both heading and body")


def wrap(draw, text, font, max_width):
    lines = []
    for para in text.split("\n"):
        if para.strip() == "":
            lines.append("")
            continue
        line = ""
        for word in para.split(" "):
            test = (line + " " + word).strip()
            if draw.textlength(test, font=font) <= max_width:
                line = test
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)
    return lines


def render_slide(slide, idx, total):
    img = Image.new("RGB", (SLIDE_W, SLIDE_H), BLACK)
    d = ImageDraw.Draw(img)

    d.text((MARGIN_X, 70), f"{idx:02d} / {total:02d}",
           font=ImageFont.truetype(FONT_REG, 26), fill=MUTED)

    h_size = 64 if slide.get("kind") in ("hook", "cta") else 54
    while True:
        h_font = ImageFont.truetype(FONT_BOLD, h_size)
        h_lines = wrap(d, slide["heading"], h_font, MAX_W)
        if len(h_lines) <= 3 or h_size <= 40:
            break
        h_size -= 2
    h_line_h = int(h_size * 1.3)
    h_block = len(h_lines) * h_line_h

    avail = (BOTTOM - TOP) - h_block - 50
    b_size = 40
    while True:
        b_font = ImageFont.truetype(FONT_REG, b_size)
        b_lines = wrap(d, slide["body"], b_font, MAX_W)
        b_line_h = int(b_size * 1.5)
        if len(b_lines) * b_line_h <= avail or b_size <= 30:
            break
        b_size -= 1

    total_h = h_block + 50 + len(b_lines) * b_line_h
    y = TOP + max(0, (BOTTOM - TOP - total_h) // 3)
    for line in h_lines:
        d.text((MARGIN_X, y), line, font=h_font, fill=GOLD)
        y += h_line_h
    y += 50
    for line in b_lines:
        d.text((MARGIN_X, y), line, font=b_font, fill=WHITE)
        y += b_line_h

    if y > BOTTOM + 20:
        raise ValueError(f"slide {idx} text overflows the slide; shorten it")
    return img


def to_reel_frame(slide_img):
    """Center the 4:5 slide on a 9:16 black canvas."""
    canvas = Image.new("RGB", (REEL_W, REEL_H), BLACK)
    canvas.paste(slide_img, (0, (REEL_H - SLIDE_H) // 2))
    return canvas


def slide_seconds(slide):
    words = len((slide["heading"] + " " + slide["body"]).split())
    return max(MIN_SECONDS, min(MAX_SECONDS, BASE_SECONDS + words / WORDS_PER_SECOND))


def build_video(frame_paths, durations, out_path):
    list_file = BUILD_DIR / "frames.txt"
    lines = []
    for p, dur in zip(frame_paths, durations):
        lines.append(f"file '{Path(p).resolve()}'")
        lines.append(f"duration {dur:.2f}")
    # concat demuxer quirk: the last file must be listed again without duration
    lines.append(f"file '{Path(frame_paths[-1]).resolve()}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-vf", f"fps={FPS},format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "64k",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr[-2000:])
        raise RuntimeError("ffmpeg failed")


def build_caption(item):
    return f"{item['caption'].strip()}\n\n.\n.\n.\n{item['hashtags'].strip()}"


def post_format():
    fmt = os.environ.get("POST_FORMAT", "carousel").strip().lower()
    if fmt not in ("carousel", "reel"):
        raise ValueError(f"POST_FORMAT must be 'carousel' or 'reel', got '{fmt}'")
    return fmt


def build_carousel(slides, out_dir):
    """One JPEG per slide (Instagram's API accepts JPEG only, not PNG), 1080x1350."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, s in enumerate(slides, 1):
        img = render_slide(s, i, len(slides))
        p = out_dir / f"slide_{i:02d}.jpg"
        img.save(p, "JPEG", quality=95, subsampling=0)
        paths.append(p)
    return paths


def generate():
    POSTS_DIR.mkdir(exist_ok=True)
    BUILD_DIR.mkdir(exist_ok=True)
    fmt = post_format()

    item = next_item()
    if item is None:
        print("::error::Content queue is empty. Add a new file to content/queue/ "
              "before the next scheduled post. Nothing was posted.")
        signal_github_output(generated=False)
        sys.exit(1)

    validate(item)
    slides = item["slides"]
    if fmt == "carousel" and len(slides) > 10:
        raise ValueError("Instagram carousels take at most 10 slides through the API")
    print(f"Building {fmt} for '{item['id']}' ({len(slides)} slides)")

    slug = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")

    if fmt == "carousel":
        paths = build_carousel(slides, POSTS_DIR / f"carousel_{slug}")
        print(f"Built {len(paths)} slide images in posts/carousel_{slug}/")
    else:
        frame_paths, durations = [], []
        for i, s in enumerate(slides, 1):
            frame = to_reel_frame(render_slide(s, i, len(slides)))
            p = BUILD_DIR / f"frame_{i:02d}.png"
            frame.save(p)
            frame_paths.append(p)
            durations.append(slide_seconds(s))
        video_path = POSTS_DIR / f"reel_{slug}.mp4"
        build_video(frame_paths, durations, video_path)
        print(f"Built {video_path} ({sum(durations):.0f}s total)")

    (POSTS_DIR / f"caption_{slug}.txt").write_text(build_caption(item), encoding="utf-8")
    (POSTS_DIR / "latest.txt").write_text(slug)
    (POSTS_DIR / "latest_item.txt").write_text(item["id"])
    (POSTS_DIR / "latest_format.txt").write_text(fmt)
    signal_github_output(generated=True)


def mark_published():
    item_id = (POSTS_DIR / "latest_item.txt").read_text().strip()
    state = load_state()
    if item_id not in state["published"]:
        state["published"].append(item_id)
        save_state(state)
    print(f"Marked '{item_id}' as published.")


if __name__ == "__main__":
    if "--mark-published" in sys.argv:
        mark_published()
    else:
        generate()
