"""
generate_image.py
------------------
Calls Google's free Gemini API to write a genuinely fresh post every time
it runs — new text, new caption, new hashtags, never repeated.

No fallback: if the Gemini call fails for any reason (rate limit, safety
block, bad response, outage), generation returns None and the caller must
skip posting for that run rather than reuse old/recycled content. There is
no static content bank — a failed run means no post that day, not a stale
repost.

Renders the result as a 1080x1080 black-background image for @rootedand.rich.
Runs automatically inside GitHub Actions, three times a day.
"""

import os
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

GEMINI_MODEL = "gemini-3.1-flash-lite"

# Google's default safety filters can silently block requests that ask for
# mild profanity, even when it's a clear, intentional style choice like this
# account's voice. This relaxes those categories so real generations don't
# get blocked and silently fall back to the static content bank.
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
]


def get_trending_topics(max_topics=5):
    """
    Pulls today's real trending search terms so Gemini has something current
    to (optionally) ground a post in, instead of only evergreen wisdom.
    Returns a plain list of strings, or [] if the fetch fails for any reason
    — never lets a trends outage break post generation.
    """
    try:
        resp = requests.get("https://trends.google.com/trending/rss?geo=US", timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        titles = [item.findtext("title") for item in root.iter("item")]
        titles = [t for t in titles if t][:max_topics]
        return titles
    except Exception as e:
        print(f"Trending topics fetch failed ({e}) — continuing without them.")
        return []

AI_PROMPT = """You're the content strategist for @rootedand.rich, and your job is to \
pick angles that actually stop the scroll for men aged 18-34 in India and the US. \
You're not a quote generator and you're not precious about sounding "nice" — you're a \
guy who's actually lived through wrestling with faith, discipline, and money, and \
you're talking straight, the way an older brother talks when he's not holding back.

Voice rules — follow these closely:
- Talk directly TO the reader using "you" — never "men" in the abstract third person
- Go informal, not middle-ground-formal. Real texting rhythm: contractions, sentence \
fragments, run-on thoughts when that's how a real person would actually say it
- {hook_instruction}
- Be opinionated and blunt, not diplomatic. Take a clear side. It's fine if not \
everyone agrees — safe, hedge-everything writing doesn't get shared
- Casual profanity is fine when it lands naturally (shit, hell, damn, ass, and mild \
uses of "f*ck" with the asterisk, the way real accounts in this space write it) — \
don't force it into every post, but don't sanitize it out either when it's the \
natural word
- If a line sounds like it belongs on a motivational poster or in a textbook, rewrite \
it rougher, blunter, more specific. Specific beats abstract every time — use real \
numbers, named items, and concrete examples instead of vague nouns. '$20,000 in \
savings' beats 'financial security.' 'Garlic, ginger, eggs, spinach' beats 'eating \
healthy.' A concrete, checkable claim always outperforms an abstract platitude.
- Keep the faith and money themes, but ground them in something specific-sounding, \
not generic wisdom. Faith-related content should still respect the topic — raw and \
irreverent in tone is fine, mocking faith itself is not.

Write ONE completely original Instagram post, different from anything written \
before, covering ONE of these themes (pick a different one each time): money \
stewardship, discipline, integrity, patience, gratitude, generosity, \
forgiveness, contentment, legacy, faith versus fear, protecting your peace, \
small beginnings, guarding your reputation, simplicity, or rest.

Structure this post using this EXACT format — this is mandatory, not optional: \
{format_instruction}

{trends_block}

Return ONLY this exact JSON object, nothing else, no markdown fences:
{{"image_text": "3-6 short lines using \\n for line breaks, sounding like real talk, \
not a polished quote", "caption": "1-3 sentences in the same direct voice, ending \
with EITHER a genuine question OR one short standalone punchline that reframes the \
whole post — vary which one you use, don't default to a question every time", "hashtags": "5-6 relevant hashtags separated \
by spaces, starting with #, always including #rootedandrich"}}
"""


def generate_via_ai():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("No GEMINI_API_KEY set — cannot generate content for this run.")
        return None

    state = load_state()
    hook_index = (state.get("last_hook_index", -1) + 1) % len(HOOK_TYPES)
    hook_instruction = (
        f"Open with this EXACT hook style and nothing else — this is mandatory, "
        f"not a suggestion: {HOOK_TYPES[hook_index]}"
    )
    format_index = (state.get("last_format_index", -1) + 1) % len(FORMAT_TYPES)
    format_instruction = FORMAT_TYPES[format_index]

    trends = get_trending_topics()
    if trends:
        trend_list = ", ".join(trends)
        trends_block = (
            f"Here's what's actually trending in the news/culture right now: "
            f"{trend_list}. ONLY use one of these as a hook or reference if it "
            f"genuinely, naturally connects to money/discipline/faith without "
            f"forcing it or sounding like a tacked-on news reference. If none of "
            f"them fit naturally, ignore this list completely and write from the "
            f"themes above instead — a forced trend tie-in is worse than none."
        )
        print(f"Grounding with today's trends: {trend_list}")
    else:
        trends_block = ""

    prompt = AI_PROMPT.format(
        trends_block=trends_block,
        hook_instruction=hook_instruction,
        format_instruction=format_instruction,
    )

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={api_key}")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.95},
        "safetySettings": SAFETY_SETTINGS,
    }

    try:
        resp = requests.post(url, json=body, timeout=30)
        resp.raise_for_status()
        response_json = resp.json()

        candidates = response_json.get("candidates", [])
        if not candidates:
            # This is the safety-block case: Gemini returns 200 OK with no
            # candidates and a promptFeedback.blockReason instead of an error.
            print(f"No candidates returned — likely safety-blocked. Full response: {response_json}")
            return None

        finish_reason = candidates[0].get("finishReason")
        if finish_reason not in (None, "STOP"):
            print(f"Generation stopped early (finishReason={finish_reason}). Full response: {response_json}")
            return None

        raw_text = candidates[0]["content"]["parts"][0]["text"]
        post = json.loads(raw_text)

        required = ["image_text", "caption", "hashtags"]
        if not all(k in post and post[k].strip() for k in required):
            print(f"AI response missing required fields — falling back to content bank. Raw: {raw_text}")
            return None

        print(f"Generated fresh content via Gemini AI. Hook: {HOOK_TYPES[hook_index]} | Format: {FORMAT_TYPES[format_index]}")
        save_state({"last_hook_index": hook_index, "last_format_index": format_index})
        return post

    except Exception as e:
        print(f"AI generation failed ({e}) — falling back to content bank.")
        return None

BLACK = "#000000"
WHITE = "#F0F0EC"
MUTED = "#6B6B65"
GOLD = "#C9A84C"
HANDLE = "@rootedand.rich"

SIZE = 1080
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

STATE_FILE = "posts/state.json"

VIRAL_HASHTAGS = "#motivation #mindset #wealth #faith #entrepreneur"


def wrap_and_measure(draw, text, font, max_width):
    all_lines = []
    for para in text.split("\n"):
        if para.strip() == "":
            all_lines.append("")
            continue
        words = para.split(" ")
        line = ""
        for word in words:
            test = (line + " " + word).strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_width:
                line = test
            else:
                if line:
                    all_lines.append(line)
                line = word
        if line:
            all_lines.append(line)
    return all_lines


def render_post(image_text, out_path):
    img = Image.new("RGB", (SIZE, SIZE), BLACK)
    draw = ImageDraw.Draw(img)

    left_margin = 150
    max_width = SIZE - (left_margin * 2)
    font_size = 38
    font = ImageFont.truetype(FONT_REG, font_size)
    line_height = int(font_size * 1.55)

    lines = wrap_and_measure(draw, image_text, font, max_width)
    start_y = int(SIZE * 0.30)

    y = start_y
    for line in lines:
        draw.text((left_margin, y), line, font=font, fill=WHITE)
        y += line_height

    img.save(out_path, "PNG", quality=100)


def render_story(image_text, out_path):
    story_width = 1080
    story_height = 1920
    img = Image.new("RGB", (story_width, story_height), BLACK)
    draw = ImageDraw.Draw(img)

    left_margin = 90
    max_width = story_width - (left_margin * 2)
    font_size = 46
    font = ImageFont.truetype(FONT_REG, font_size)
    line_height = int(font_size * 1.55)

    lines = wrap_and_measure(draw, image_text, font, max_width)
    total_h = len(lines) * line_height

    safe_top = int(story_height * 0.25)
    safe_bottom = int(story_height * 0.80)
    safe_height = safe_bottom - safe_top
    start_y = safe_top + max(0, (safe_height - total_h) // 2)

    y = start_y
    for line in lines:
        draw.text((left_margin, y), line, font=font, fill=WHITE)
        y += line_height

    img.save(out_path, "PNG", quality=100)


HOOK_TYPES = [
    "a bold flat claim stated like a fact (e.g. 'I guarantee you—')",
    "a single-word or short label callout in caps (e.g. 'TRUTH:' or 'FACT:')",
    "a blunt direct order or command, NOT starting with the word 'Stop' — use a different verb "
    "(e.g. 'Cut the—', 'Kill the—', 'Burn the—', 'Drop the—')",
    "a myth-bust opener (e.g. 'Nobody tells you this, but—')",
    "dropping straight into the middle of a thought with no setup at all, no label, no command",
]

FORMAT_TYPES = [
    "a numbered listicle (e.g. '5 things that separate men who make it from men who "
    "don't:') followed by 4-6 short numbered items, ending with ONE standalone punchline "
    "sentence after the list that ties it together",
    "parallel repetition structure: the same short sentence shape repeated 3-4 times back "
    "to back (e.g. 'Be rich. But never talk about money. Be sharp. But never announce it.'), "
    "ending on a single short standalone line that breaks the pattern",
    "a short punchy multi-line statement, 3-5 lines, building to one hard final line that "
    "recontextualizes everything before it",
    "a single dense paragraph (3-4 sentences, no line breaks) that reads like a real "
    "thought someone typed out fast, ending on one short standalone sentence",
    "binary contrast structure: one bold declarative opening line, then 2-4 tight supporting "
    "lines using CONCRETE specifics — real numbers, named items, actual examples, never vague "
    "abstractions (e.g. '$20,000 in savings' not 'financial security', 'garlic, ginger, eggs' "
    "not 'healthy food') — then a short contrast pair ('Weak men do X. Strong men do Y.') or a "
    "punchline that reframes the whole post in one line",
]


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"last_hook_index": -1, "last_format_index": -1}


def save_state(updates: dict):
    """Merges into the existing state file instead of overwriting it, so the
    hook-rotation and format-rotation indices don't clobber each other when
    only one of them changes in a given run."""
    state = load_state()
    state.update(updates)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def signal_github_output(generated: bool):
    """Lets the GitHub Actions workflow know whether a post was actually
    generated, so it can skip the commit/publish steps on a no-op run
    instead of failing or, worse, posting nothing found and erroring out."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"generated={'true' if generated else 'false'}\n")


def main():
    os.makedirs("posts", exist_ok=True)

    post = generate_via_ai()

    if post is None:
        print("Gemini generation failed — skipping this run entirely. "
              "No fallback content, no repost. Next scheduled run will try again.")
        signal_github_output(generated=False)
        return

    now = datetime.now(timezone.utc)
    slug = now.strftime("%Y-%m-%d_%H%M%S")

    image_path = f"posts/post_{slug}.png"
    story_path = f"posts/story_{slug}.png"
    caption_path = f"posts/caption_{slug}.txt"

    render_post(post["image_text"], image_path)
    render_story(post["image_text"], story_path)

    full_caption = f"{post['caption']}\n\n.\n.\n.\n{post['hashtags']} {VIRAL_HASHTAGS}"
    with open(caption_path, "w", encoding="utf-8") as f:
        f.write(full_caption)

    with open("posts/latest.txt", "w") as f:
        f.write(slug)

    signal_github_output(generated=True)
    print(f"Generated {image_path} and {story_path}")


if __name__ == "__main__":
    main()
