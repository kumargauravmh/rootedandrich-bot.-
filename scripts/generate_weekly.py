"""
generate_weekly.py
------------------
Takes the winning posts from data/trends.json and writes 7 ORIGINAL posts
(one per day, Mon-Sun of the coming week) that carry the same core idea /
emotional hit in fresh wording. Renders each as a 1080x1920 black reel-format
image and saves everything under weekly/<monday-date>/.

A post that reuses a 5-word run from its source (or from another post this
week) is rejected and regenerated. If a slot still fails after retries it is
skipped and reported - never filled with recycled content.

Env: GEMINI_API_KEY
"""

import os
import re
import sys
import json
import random
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gemini_util

W, H = 1080, 1920
BLACK = "#000000"
WHITE = "#F0F0EC"
# Text lives inside a centered box so it also sits inside the profile-grid crop
# (1:1 / 4:5 / 3:4 center crops all contain y=420..1500 and x=150..930).
BOX_L, BOX_R = 150, 930
BOX_T, BOX_B = 440, 1480
START_SIZE, MIN_SIZE = 46, 28
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]

BROAD_POOL = ["#motivation", "#mindset", "#wealth", "#discipline", "#selfimprovement", "#masculinity", "#entrepreneur"]
TOTAL_HASHTAGS = 5   # Instagram allows max 5 per post


def build_hashtags(specific):
    """3 specific from the model + broad ones to make exactly 5. Never more than 5."""
    tags = []
    for t in specific.split():
        t = t if t.startswith("#") else "#" + t
        if t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    tags = tags[:3]
    for t in random.sample(BROAD_POOL, len(BROAD_POOL)):
        if len(tags) >= TOTAL_HASHTAGS:
            break
        if t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    return " ".join(tags[:TOTAL_HASHTAGS])
OVERLAP_N = 8   # reject only if 8+ consecutive words match the source (same words are OK, same sentences are not)
DAYS = 7
RETRIES = 2            # attempts per source post
MAX_SOURCES_PER_DAY = 4  # if a source keeps failing, try other source posts before giving up on a day

HOOK_STYLES = [
    "a bold flat claim that sounds like a guarantee",
    "a one-word label followed by the point (like TRUTH: or REAL TALK:)",
    "a blunt direct order to the reader",
    "a myth-bust that attacks something most guys believe",
    "dropping mid-thought, like you're continuing an argument",
    "a question that stings because the answer is obvious",
    "a hard comparison between two types of men",
]

PROMPT = """You write posts for @rootedand.rich: raw, blunt, no-bullshit content for men \
aged 18-34 in India and the US about money, discipline, faith, relationships and self-respect. \
You talk like an older brother who isn't holding back - not like a motivational poster.

Below is a post that is performing very well on a similar page. It is ONLY an idea reference.

--- SOURCE POST ---
Text on the image:
{image_text}

Caption:
{caption}

Performance: {likes} likes, {comments} comments on a {followers}-follower page ({rate}% engagement).
--- END SOURCE ---

Already written for this week's batch (do NOT repeat these ideas, openings or phrases):
{avoid}

STEP 1 (think silently): what is the core idea, and what exact emotion makes men like/share/save it \
(shame, anger, validation, fear of wasting time, desire for respect...)?
STEP 2: write a NEW post that hits the same idea and the same emotion, in the same kind of words the source uses.

Closeness rules (hard):
- Stay close to the source's vocabulary. Keep its everyday words and its punchiest short phrases wherever they work, so the post feels like a sibling of the source: same energy, same kind of words.
- You can reuse key words and short phrases (up to 6 words in a row). Do NOT copy whole sentences. NEVER reuse 8 or more words in a row.
- Change enough that it's not a clone: reorder the lines, rewrite at least half of them, and swap in at least one different concrete detail or example.
- Opening line style: {hook}. But if the source's opening is the reason it works, keep that same kind of opening in your own words.
- Plain words only. Write like you're texting a friend. No textbook, corporate or self-help-book words (no stewardship, resilience, cultivate, endeavor, navigate, journey, fulfillment). If a simpler word exists, use it.
- Never mention the source, the page, or that this is inspired by anything.

Voice rules:
- Talk TO the reader ("you"). Texting rhythm: fragments, contractions, short punchy lines.
- Swear freely when it's the natural word (fuck, shit, damn, ass, hell). Don't force it, don't sanitize it.
- Sex, lust, women and relationships are fair game when blunt and relatable, but nothing graphic or \
pornographic. No slurs. No hate toward any group. Don't mock anyone's faith.
- Specific beats abstract. If a line could sit on a motivational poster, rewrite it rougher.
- Take a side. No hedging.

Format:
- image_text: 25-55 words total, 4-9 short lines separated by \\n. First line is the hook.
- caption: 1-2 sentences that add one extra angle (not a repeat of the image), may end with a question.
- hashtags: exactly 3 specific hashtags relevant to this post's topic, each starting with #.

Return ONLY this JSON, nothing else:
{{"image_text": "...", "caption": "...", "hashtags": "#a #b #c"}}
"""


# ---------- originality check ----------

def tokens(text):
    return re.findall(r"[a-z0-9']+", text.lower())


def ngrams(words, n):
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def shares_run(candidate, others, n):
    cand = ngrams(tokens(candidate), n)
    for o in others:
        if cand & ngrams(tokens(o), n):
            return True
    return False


# ---------- rendering ----------

def load_font(size):
    for p in FONT_PATHS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def wrap(draw, text, font, max_width):
    out = []
    for para in text.split("\n"):
        if not para.strip():
            out.append("")
            continue
        line = ""
        for word in para.split(" "):
            test = (line + " " + word).strip()
            if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
                line = test
            else:
                if line:
                    out.append(line)
                line = word
        if line:
            out.append(line)
    return out


def render(image_text, out_path):
    img = Image.new("RGB", (W, H), BLACK)
    draw = ImageDraw.Draw(img)
    max_w = BOX_R - BOX_L
    box_h = BOX_B - BOX_T

    size = START_SIZE
    while True:
        font = load_font(size)
        lines = wrap(draw, image_text, font, max_w)
        lh = int(size * 1.5)
        if len(lines) * lh <= box_h or size <= MIN_SIZE:
            break
        size -= 2

    y = BOX_T + max(0, (box_h - len(lines) * lh) // 2)   # block centered vertically in the box
    for line in lines:
        draw.text((BOX_L, y), line, font=font, fill=WHITE)
        y += lh
    img.save(out_path, "PNG")


# ---------- generation ----------

def clean(text):
    return text.replace("\\n", "\n").strip()


def make_post(src, hook, done_texts):
    prompt = PROMPT.format(
        image_text=src.get("image_text") or "(no text on image)",
        caption=src.get("caption") or "(none)",
        likes=src["likes"], comments=src["comments"],
        followers=f"{src['followers']:,}", rate=src["rate"], hook=hook,
        avoid="\n".join("- " + t.replace("\n", " / ") for t in done_texts) or "(nothing yet)",
    )
    source_text = [src.get("image_text", ""), src.get("caption", "")]
    last_problem = "unknown"

    for attempt in range(1, RETRIES + 1):
        try:
            raw = gemini_util.call([{"text": prompt}], json_mode=True, temperature=0.95)
            post = json.loads(raw)
            for k in ("image_text", "caption", "hashtags"):
                if not str(post.get(k, "")).strip():
                    raise ValueError(f"missing field {k}")
            post["image_text"] = clean(post["image_text"])
            post["caption"] = clean(post["caption"])
            post["hashtags"] = post["hashtags"].strip()
            words = len(post["image_text"].split())
            if not 15 <= words <= 70:
                raise ValueError(f"image_text length {words} words")
            full = post["image_text"] + " " + post["caption"]
            if shares_run(full, source_text, OVERLAP_N):
                raise ValueError("too close to source wording")
            if shares_run(post["image_text"], done_texts, 7):
                raise ValueError("repeats another post this week")
            return post, None
        except Exception as e:
            last_problem = str(e)
            print(f"   attempt {attempt} rejected: {last_problem}")
    return None, last_problem


def pick_start():
    """Week runs Sunday -> Saturday. Saturday's run covers the Sunday that follows.
    A START_DATE (YYYY-MM-DD) can be given when running manually."""
    forced = os.environ.get("START_DATE", "").strip()
    if forced:
        return datetime.strptime(forced, "%Y-%m-%d").date()
    d = datetime.now(timezone.utc).date() + timedelta(days=1)
    while d.weekday() != 6:   # 6 = Sunday
        d += timedelta(days=1)
    return d


def main():
    with open("data/trends.json", encoding="utf-8") as f:
        winners = json.load(f)["winners"]
    if not winners:
        sys.exit("data/trends.json has no winners")

    random.shuffle(winners)
    hooks = HOOK_STYLES[:]
    random.shuffle(hooks)

    start = pick_start()
    out_dir = f"weekly/{start.isoformat()}"
    os.makedirs(out_dir, exist_ok=True)

    posts, done_texts, failures, used = [], [], [], {}
    for i in range(DAYS):
        day = start + timedelta(days=i)
        label = f"Day {i + 1} ({day.strftime('%a %d %b')})"
        # least-used sources first, so a stubborn source never blocks a day
        order = sorted(range(len(winners)), key=lambda k: (used.get(k, 0), (k - i) % len(winners)))
        post, reasons = None, []
        for tries, k in enumerate(order[:MAX_SOURCES_PER_DAY]):
            src = winners[k]
            hook = hooks[(i + tries) % len(hooks)]
            print(f"{label}: idea from @{src['account']} ({src['rate']}%)")
            post, problem = make_post(src, hook, done_texts)
            if post:
                used[k] = used.get(k, 0) + 1
                break
            reasons.append(f"@{src['account']}: {problem}")
            print(f"   rejected: {problem}")
        if post is None:
            failures.append({"day": i + 1, "date": day.isoformat(), "weekday": day.strftime("%A"), "reasons": reasons})
            print(f"   GIVING UP on {label}")
            continue
        done_texts.append(post["image_text"])
        img_path = f"{out_dir}/day{i + 1}_{day.strftime('%a').lower()}.png"
        render(post["image_text"], img_path)
        posts.append({
            "day": i + 1,
            "date": day.isoformat(),
            "weekday": day.strftime("%A"),
            "image": img_path,
            "image_text": post["image_text"],
            "caption": post["caption"],
            "hashtags": build_hashtags(post["hashtags"]),
            "idea_from": src["account"],
            "idea_permalink": src.get("permalink"),
            "source_text": src.get("image_text", ""),
            "source_caption": src.get("caption", ""),
            "source_stats": f"{src['likes']:,} likes, {src['comments']:,} comments, "
                            f"{src['rate']}% engagement on a {src['followers']:,}-follower page",
        })

    with open(f"{out_dir}/report.json", "w", encoding="utf-8") as f:
        json.dump({"failures": failures}, f, indent=2, ensure_ascii=False)

    if not posts:
        sys.exit("No posts generated this week - check the errors above.")

    with open(f"{out_dir}/week.json", "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)
    with open("weekly/latest.txt", "w") as f:
        f.write(out_dir)

    print(f"\nGenerated {len(posts)}/{DAYS} posts in {out_dir}")
    if len(posts) < DAYS:
        print("WARNING: some days are missing - they were skipped, not filled with recycled content.")


if __name__ == "__main__":
    main()
