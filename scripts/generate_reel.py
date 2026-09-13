"""
generate_reel.py
------------------
Reuses generate_image.py's exact content pipeline (Gemini call, content-bank
fallback, state tracking) and swaps only the rendering step: instead of a
static 1080x1080 PNG, this builds a 1080x1920 vertical video with a TTS
voiceover and line-by-line text reveal, for posting as a Reel.

Requires: pillow, edge-tts, requests  (pip install -r requirements.txt)
Requires: ffmpeg on PATH (preinstalled on GitHub Actions ubuntu-latest runners)
"""

import asyncio
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageFont

# Reuse everything from your existing pipeline — same Gemini prompt, same
# content bank fallback, same state file, so this can't drift out of sync
# with generate_image.py.
from generate_image import (
    generate_via_ai,
    load_state,
    save_state,
    CONTENT_BANK,
    FONT_REG,
    VIRAL_HASHTAGS,
)

# ---- Video-specific config ----
WIDTH, HEIGHT = 1080, 1920
BLACK = (0, 0, 0)
WHITE = (240, 240, 236)  # matches WHITE = "#F0F0EC" in generate_image.py
LEFT_MARGIN = 90
FONT_SIZE = 52
LINE_SPACING = 22
FPS = 30

# en-US-ChristopherNeural = deep, casual male voice. Run
# `edge-tts --list-voices` to browse other options.
TTS_VOICE = "en-US-ChristopherNeural"
TTS_RATE = "+0%"


def wrap_text(text, font, max_width):
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = (current + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


async def generate_voiceover(text: str, out_path: str) -> float:
    # Strip newlines for natural speech pacing — TTS reads punctuation for pauses
    speech_text = text.replace("\n", " ").strip()
    communicate = edge_tts.Communicate(speech_text, TTS_VOICE, rate=TTS_RATE)
    await communicate.save(out_path)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", out_path],
        capture_output=True, text=True, check=True
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def render_cover_image(image_text: str, out_path: str):
    font = ImageFont.truetype(FONT_REG, FONT_SIZE)
    max_width = WIDTH - (2 * LEFT_MARGIN)

    wrapped_lines = []
    for para in image_text.split("\n"):
        if para.strip() == "":
            wrapped_lines.append("")
        else:
            wrapped_lines.extend(wrap_text(para, font, max_width))

    n_lines = len(wrapped_lines)
    line_height = FONT_SIZE + LINE_SPACING
    block_height = n_lines * line_height
    start_y = (HEIGHT - block_height) // 2

    img = Image.new("RGB", (WIDTH, HEIGHT), BLACK)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(wrapped_lines):
        if line:
            y = start_y + i * line_height
            draw.text((LEFT_MARGIN, y), line, font=font, fill=WHITE)
    img.save(out_path)


def assemble_video(cover_image_path: str, audio_path: str, out_path: str, duration: float):
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", cover_image_path,
        "-i", audio_path,
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(duration),
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def build_reel(image_text: str, out_path: str, work_dir: str = "reel_build"):
    work = Path(work_dir)
    work.mkdir(exist_ok=True)
    audio_path = str(work / "voiceover.mp3")
    cover_path = str(work / "cover.png")

    duration = asyncio.run(generate_voiceover(image_text, audio_path))
    # small pad so the last word isn't cut off right at the audio's edge
    duration += 0.5

    render_cover_image(image_text, cover_path)
    assemble_video(cover_path, audio_path, out_path, duration)
    return duration


def main():
    os.makedirs("posts", exist_ok=True)

    post = generate_via_ai()

    if post is None:
        state = load_state()
        next_index = (state["last_index"] + 1) % len(CONTENT_BANK)
        post = CONTENT_BANK[next_index]
        save_state({"last_index": next_index})
        print(f"Using content bank fallback (index {next_index} of {len(CONTENT_BANK)})")

    now = datetime.now(timezone.utc)
    slug = now.strftime("%Y-%m-%d_%H%M%S")

    video_path = f"posts/reel_{slug}.mp4"
    caption_path = f"posts/caption_{slug}.txt"

    duration = build_reel(post["image_text"], video_path)
    print(f"Built {video_path} ({duration:.1f}s)")

    full_caption = f"{post['caption']}\n\n.\n.\n.\n{post['hashtags']} {VIRAL_HASHTAGS}"
    with open(caption_path, "w", encoding="utf-8") as f:
        f.write(full_caption)

    with open("posts/latest.txt", "w") as f:
        f.write(slug)

    print(f"Generated {video_path}")


if __name__ == "__main__":
    main()
