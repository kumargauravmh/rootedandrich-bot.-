"""
single_reel.py
---------------
Turns the next queued item into ONE still frame shown as a short silent Reel
(no voiceover, no slides): a hook, five key points, and a closing question.

Why one frame: every fact is on screen at once, so a viewer can read it, screenshot
it, or rewatch the loop. Layout is built around Instagram's Reels interface:
  - nothing in the top ~290px or bottom ~420px (covered by buttons/caption)
  - nothing in the right ~130px (like/share buttons)
  - the hook starts at y=290 so it is also visible in the 4:5 crop of the profile grid

Writes what post_reel.py expects:
  posts/reel_<slug>.mp4, posts/caption_<slug>.txt, posts/latest.txt, posts/latest_item.txt

Usage:
  python scripts/single_reel.py                   # build the next queued reel
  python scripts/single_reel.py --mark-published  # call AFTER a successful post

No fallback content: an empty queue fails the run loudly (you get a GitHub email).
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

QUEUE_DIR = Path("content/queue")
STATE_FILE = Path("content/state.json")
POSTS_DIR = Path("posts")
BUILD_DIR = Path("reel_build")
IST = ZoneInfo("Asia/Kolkata")

W, H = 1080, 1920
LEFT = 90
RIGHT_MARGIN = 130
TEXT_W = W - LEFT - RIGHT_MARGIN          # 860
SAFE_TOP = 290
SAFE_BOTTOM = 1500
NUM_INDENT = 58                            # room for the gold point numbers

BLACK = (0, 0, 0)
WHITE = (240, 240, 236)
GOLD = (201, 168, 76)
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# base font sizes at scale 1.0; the fitter shrinks everything together if needed
HOOK_SIZE, POINT_SIZE, CLOSER_SIZE = 66, 36, 38
MIN_SCALE = 0.78
HOOK_MAX_LINES = 4

# how long the frame stays on screen: reading time, clamped
MIN_SECONDS, MAX_SECONDS = 10.0, 20.0
WORDS_PER_SECOND = 4.5
BASE_SECONDS = 4.0
FPS = 30

N_POINTS = 5


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------
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


def is_single_format(item):
    return bool(item.get("hook")) and isinstance(item.get("points"), list)


def next_item():
    """First queue file (alphabetical) not yet published and in the one-frame format."""
    state = load_state()
    for path in sorted(QUEUE_DIR.glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        if item.get("id") in state["published"]:
            continue
        if not is_single_format(item):
            print(f"Skipping {path.name}: old multi-slide format, not postable as a one-frame reel.")
            continue
        return item
    return None


def validate_single(item):
    for key in ("id", "caption", "hashtags", "hook", "points", "closer"):
        if not item.get(key):
            raise ValueError(f"queue item is missing '{key}'")
    if len(item["points"]) != N_POINTS:
        raise ValueError(f"need exactly {N_POINTS} points, got {len(item['points'])}")
    if not all(isinstance(p, str) and p.strip() for p in item["points"]):
        raise ValueError("every point must be non-empty text")


def total_words(item):
    texts = [item["hook"], *item["points"], item["closer"]]
    return sum(len(t.split()) for t in texts)


def single_seconds(item):
    return max(MIN_SECONDS, min(MAX_SECONDS, BASE_SECONDS + total_words(item) / WORDS_PER_SECOND))


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def wrap(draw, text, font, max_width):
    lines, line = [], ""
    for word in text.split():
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


def layout(draw, item, scale):
    """Returns (blocks, total_height) for a given font scale, or None if the hook is too long."""
    f_hook = ImageFont.truetype(FONT_BOLD, round(HOOK_SIZE * scale))
    f_pt = ImageFont.truetype(FONT_REG, round(POINT_SIZE * scale))
    f_num = ImageFont.truetype(FONT_BOLD, round(POINT_SIZE * scale))
    f_close = ImageFont.truetype(FONT_BOLD, round(CLOSER_SIZE * scale))

    hook_lines = wrap(draw, item["hook"], f_hook, TEXT_W)
    if len(hook_lines) > HOOK_MAX_LINES:
        return None
    hook_lh = int(f_hook.size * 1.22)
    pt_lh = int(f_pt.size * 1.32)
    close_lh = int(f_close.size * 1.3)

    blocks = [("hook", hook_lines, f_hook, hook_lh)]
    y = len(hook_lines) * hook_lh + int(34 * scale)          # hook + gap + divider
    y += int(40 * scale)
    for i, p in enumerate(item["points"], 1):
        lines = wrap(draw, p, f_pt, TEXT_W - NUM_INDENT)
        blocks.append(("point", (i, lines), (f_num, f_pt), pt_lh))
        y += len(lines) * pt_lh + int(22 * scale)
    close_lines = wrap(draw, item["closer"], f_close, TEXT_W)
    blocks.append(("closer", close_lines, f_close, close_lh))
    y += int(18 * scale) + len(close_lines) * close_lh
    return blocks, y, scale


def render_single(item):
    """Returns the 1080x1920 frame. Raises ValueError if the text cannot fit the safe area."""
    validate_single(item)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    avail = SAFE_BOTTOM - SAFE_TOP

    chosen = None
    scale = 1.0
    while scale >= MIN_SCALE - 1e-9:
        res = layout(probe, item, scale)
        if res is not None and res[1] <= avail:
            chosen = res
            break
        scale = round(scale - 0.02, 2)
    if chosen is None:
        raise ValueError("text does not fit one frame; shorten the hook or the points")

    blocks, _, scale = chosen
    img = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(img)
    y = SAFE_TOP

    for kind, content, fonts, lh in blocks:
        if kind == "hook":
            for line in content:
                d.text((LEFT, y), line, font=fonts, fill=GOLD)
                y += lh
            y += int(34 * scale)
            d.rectangle([LEFT, y, LEFT + 120, y + 5], fill=GOLD)   # short gold rule
            y += int(40 * scale)
        elif kind == "point":
            n, lines = content
            f_num, f_pt = fonts
            d.text((LEFT, y), str(n), font=f_num, fill=GOLD)
            for line in lines:
                d.text((LEFT + NUM_INDENT, y), line, font=f_pt, fill=WHITE)
                y += lh
            y += int(22 * scale)
        else:  # closer
            y += int(18 * scale)
            for line in content:
                d.text((LEFT, y), line, font=fonts, fill=WHITE)
                y += lh
    return img


def build_video(frame_path, seconds, out_path):
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(FPS), "-i", str(frame_path),
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", f"{seconds:.2f}",
        "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "64k", "-shortest", "-movflags", "+faststart",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr[-2000:])
        raise RuntimeError("ffmpeg failed")


def build_caption(item):
    return f"{item['caption'].strip()}\n\n.\n.\n.\n{item['hashtags'].strip()}"


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------
def generate():
    POSTS_DIR.mkdir(exist_ok=True)
    BUILD_DIR.mkdir(exist_ok=True)

    item = next_item()
    if item is None:
        print("::error::Content queue is empty. Nothing was posted. Run 'Research Next Carousel' "
              "(dry_run=false) or add a file to content/queue/.")
        signal_github_output(generated=False)
        sys.exit(1)

    print(f"Building one-frame reel for '{item['id']}' ({total_words(item)} words)")
    frame = render_single(item)
    frame_path = BUILD_DIR / "frame.png"
    frame.save(frame_path)

    slug = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    seconds = single_seconds(item)
    video_path = POSTS_DIR / f"reel_{slug}.mp4"
    build_video(frame_path, seconds, video_path)

    (POSTS_DIR / f"caption_{slug}.txt").write_text(build_caption(item), encoding="utf-8")
    (POSTS_DIR / "latest.txt").write_text(slug)
    (POSTS_DIR / "latest_item.txt").write_text(item["id"])
    (POSTS_DIR / "latest_format.txt").write_text("reel")
    signal_github_output(generated=True)
    print(f"Built {video_path} ({seconds:.0f}s, silent)")


def mark_published(now=None):
    item_id = (POSTS_DIR / "latest_item.txt").read_text().strip()
    state = load_state()
    if item_id not in state["published"]:
        state["published"].append(item_id)
    # lets the posting gate refuse a second post on the same IST day
    state["last_posted_ist"] = (now or datetime.now(IST)).date().isoformat()
    save_state(state)
    print(f"Marked '{item_id}' as published ({state['last_posted_ist']} IST).")


if __name__ == "__main__":
    if "--mark-published" in sys.argv:
        mark_published()
    else:
        generate()
