"""
generate_reel.py
Converts a block of text (from Gemini) into a vertical (1080x1920) Reel:
black background, left-aligned text, line-by-line reveal, TTS voiceover.

Drop this into scripts/ alongside your existing analytics.py.
Requires: pillow, edge-tts  (pip install pillow edge-tts --break-system-packages)
Requires: ffmpeg on PATH (already on GitHub Actions ubuntu-latest runners)
"""

import asyncio
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageFont

# ---- Config: tune these to match your existing brand look ----
WIDTH, HEIGHT = 1080, 1920
BG_COLOR = (0, 0, 0)
TEXT_COLOR = (255, 255, 255)
FONT_SIZE = 58                     # scaled up from 38px for 1080-wide canvas
FONT_PATH = "assets/font.ttf"      # point this at whatever font your PNG pipeline used
LEFT_MARGIN = 90
LINE_SPACING = 20
FPS = 30

# Pick a voice with some grit/casualness. Full list: `edge-tts --list-voices`
# en-US-ChristopherNeural = deep, casual male. Swap freely.
TTS_VOICE = "en-US-ChristopherNeural"
TTS_RATE = "+0%"


def load_font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        # fallback so the script still runs before you've added your font file
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size
        )


def wrap_text(text, font, max_width):
    """Wrap text to fit within max_width, return list of lines."""
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = (current + " " + word).strip()
        w = draw.textlength(trial, font=font)
        if w <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


async def generate_voiceover(text: str, out_path: str) -> float:
    """Generate TTS audio, return its duration in seconds."""
    communicate = edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE)
    await communicate.save(out_path)
    # get duration via ffprobe
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", out_path],
        capture_output=True, text=True
    )
    duration = float(json.loads(result.stdout)["format"]["duration"])
    return duration


def render_frames(lines, frames_dir: Path, total_frames: int):
    """
    Render one frame per animation step: lines reveal progressively,
    evenly spaced across total_frames.
    """
    frames_dir.mkdir(parents=True, exist_ok=True)
    font = load_font(FONT_SIZE)
    max_text_width = WIDTH - (2 * LEFT_MARGIN)

    wrapped_lines = []
    for line in lines:
        wrapped_lines.extend(wrap_text(line, font, max_text_width) or [""])

    n_lines = len(wrapped_lines)
    # frame index at which each line should appear
    reveal_points = [
        int((i / max(n_lines, 1)) * total_frames) for i in range(n_lines)
    ]

    line_height = FONT_SIZE + LINE_SPACING
    block_height = n_lines * line_height
    start_y = (HEIGHT - block_height) // 2

    for f in range(total_frames):
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        for i, line in enumerate(wrapped_lines):
            if f >= reveal_points[i]:
                y = start_y + i * line_height
                draw.text((LEFT_MARGIN, y), line, font=font, fill=TEXT_COLOR)
        img.save(frames_dir / f"frame_{f:05d}.png")


def assemble_video(frames_dir: Path, audio_path: str, out_path: str, fps: int):
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-i", audio_path,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        out_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def build_reel(text: str, out_path: str, work_dir: str = "reel_build"):
    work = Path(work_dir)
    work.mkdir(exist_ok=True)
    audio_path = str(work / "voiceover.mp3")
    frames_dir = work / "frames"

    duration = asyncio.run(generate_voiceover(text, audio_path))
    total_frames = max(int(duration * FPS), FPS)  # at least 1 second

    lines = [l.strip() for l in text.split("\n") if l.strip()] or [text]
    render_frames(lines, frames_dir, total_frames)
    assemble_video(frames_dir, audio_path, out_path, FPS)

    return out_path, duration


if __name__ == "__main__":
    # Example / smoke test — replace with your Gemini output in production
    sample_text = (
        "Discipline is choosing what you want most over what you want now. "
        "Nobody is coming to save you. Build the life yourself."
    )
    path, dur = build_reel(sample_text, "output_reel.mp4")
    print(f"Built {path} — duration {dur:.2f}s")
