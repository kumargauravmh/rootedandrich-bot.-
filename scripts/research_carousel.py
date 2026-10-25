"""
research_carousel.py
---------------------
Researches the next figure in content/topics.json and writes a ready-to-post
carousel into content/queue/ (the file carousel_reel.py posts from).

How it keeps facts honest (this is the whole point of the script):
  1. It downloads real source text (Wikipedia, plus any extra public-domain
     URLs listed for that figure).
  2. Gemini may ONLY use that text, and must attach a word-for-word excerpt
     ("evidence") to every slide.
  3. The script then checks, in plain code, that each excerpt really appears
     in the source and that every number on a slide appears in the source.
     Any slide that fails -> the whole attempt is rejected and retried with
     feedback (max 3 attempts per figure).
  4. Slide text is test-rendered, so overflowing slides are rejected too.

If nothing passes, NOTHING is queued and the run fails loudly (GitHub emails
you). There is no fallback content, by design.

Usage:
  python scripts/research_carousel.py                 # next figure, writes to queue
  python scripts/research_carousel.py --dry-run       # print draft, write nothing
  python scripts/research_carousel.py --figure "Seneca the Younger"

Env: GEMINI_API_KEY (required), RESEARCH_MODEL (optional)
"""

import json
import os
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import requests

from carousel_reel import QUEUE_DIR, render_slide, validate  # same folder

TOPICS_FILE = Path("content/topics.json")
STATE_FILE = Path("content/research_state.json")
REVIEW_FILE = Path("review_issue.md")
REVIEW_TITLE_FILE = Path("review_title.txt")

GEMINI_MODEL = os.environ.get("RESEARCH_MODEL", "gemini-3.1-flash-lite")
USER_AGENT = "RootedAndRichResearchBot/1.0 (https://github.com/kumargauravmh/rootedandrich-bot.-)"

MAX_SOURCE_CHARS = 60000
MAX_ATTEMPTS_PER_FIGURE = 3
MAX_FIGURES_PER_RUN = 3
MAX_FAILURES_BEFORE_SKIP = 2

N_SLIDES = 10
MIN_EVIDENCE_WORDS = 6   # keep in sync with the "6-30 words" instruction in the prompt
MAX_HEADING_WORDS = 12
MAX_BODY_WORDS = 48
CTA_LINE = "Save this. Send it to the guy who needs it."

BROAD_HASHTAGS = "#motivation #mindset #wealth #faith #entrepreneur"


# --------------------------------------------------------------------------
# Fetching sources
# --------------------------------------------------------------------------
class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "header"):
            self._skip += 1
        if tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw_html):
    p = _TextExtractor()
    p.feed(raw_html)
    return re.sub(r"\n{3,}", "\n\n", "".join(p.parts)).strip()


def cut(text, limit):
    if len(text) <= limit:
        return text
    cut_at = text.rfind("\n", 0, limit)
    return text[: cut_at if cut_at > limit * 0.7 else limit]


def fetch_wikipedia(title):
    resp = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query", "prop": "extracts", "explaintext": 1,
            "exsectionformat": "plain", "redirects": 1, "format": "json",
            "titles": title,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    pages = resp.json()["query"]["pages"]
    page = next(iter(pages.values()))
    if "missing" in page or not page.get("extract"):
        raise ValueError(f"Wikipedia has no article titled '{title}'")
    url = "https://en.wikipedia.org/wiki/" + quote(page["title"].replace(" ", "_"))
    return page["title"], cut(page["extract"], MAX_SOURCE_CHARS), url


def fetch_extra(url):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return cut(html_to_text(resp.text), MAX_SOURCE_CHARS)


def gather_sources(figure):
    """Returns (combined_text_for_model, sources_list[{title,url}])."""
    title, text, url = fetch_wikipedia(figure["title"])
    blocks = [f"=== SOURCE 1: Wikipedia, '{title}' ===\n{text}"]
    sources = [{"title": f"Wikipedia: {title}", "url": url}]
    for i, extra in enumerate(figure.get("extra_sources", []), start=2):
        try:
            blocks.append(f"=== SOURCE {i}: {extra} ===\n{fetch_extra(extra)}")
            sources.append({"title": extra, "url": extra})
        except Exception as e:  # an extra source failing must not kill the run
            print(f"Skipping extra source {extra}: {e}")
    return "\n\n".join(blocks), sources


# --------------------------------------------------------------------------
# Verification (plain code, no AI)
# --------------------------------------------------------------------------
def norm(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def evidence_ok(evidence, source_norm):
    n = norm(evidence)
    return len(n.split()) >= MIN_EVIDENCE_WORDS and n in source_norm


def numbers_in(text):
    return [m.rstrip(".,") for m in re.findall(r"\d[\d,]*\.?\d*", text)]


_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 10**6, "billion": 10**9}


def word_numbers(text):
    """Numbers the source writes in words ('thirteen', 'forty-two', 'two hundred'),
    so a slide saying '13' isn't rejected when the source says 'thirteen'."""
    tokens = re.findall(r"[a-z]+", text.lower().replace("-", " ")) + [""]
    found, cur, total, active = set(), 0, 0, False
    for tok in tokens:
        if tok in _UNITS:
            cur += _UNITS[tok]
            active = True
        elif tok in _TENS:
            cur += _TENS[tok]
            active = True
        elif tok in _SCALES and active:
            if tok == "hundred":
                cur = (cur or 1) * 100
            else:
                total += (cur or 1) * _SCALES[tok]
                cur = 0
        else:
            if active:
                found.add(total + cur)
            cur, total, active = 0, 0, False
    return found


def numbers_ok(text, source_flat, source_words=frozenset()):
    """Every number on the slide must appear in the source, as digits (commas
    ignored) or as words. Returns the numbers that could not be found."""
    missing = []
    for num in numbers_in(text):
        digits = num.replace(",", "")
        if re.search(r"(?<!\d)" + re.escape(digits) + r"(?!\d)", source_flat):
            continue
        try:
            if float(digits) in source_words:
                continue
        except ValueError:
            pass
        missing.append(num)
    return missing


def validate_draft(data, source_text):
    """Returns a list of problems. Empty list = the draft is acceptable."""
    problems = []
    source_norm = norm(source_text)
    source_flat = re.sub(r"(?<=\d),(?=\d)", "", source_text)
    source_words = word_numbers(source_text)

    slides = data.get("slides")
    if not isinstance(slides, list) or len(slides) != N_SLIDES:
        return [f"need exactly {N_SLIDES} slides, got "
                f"{len(slides) if isinstance(slides, list) else 'none'}"]

    for i, s in enumerate(slides, start=1):
        heading = (s.get("heading") or "").strip()
        body = (s.get("body") or "").strip()
        evidence = (s.get("evidence") or "").strip()
        is_last = i == N_SLIDES

        if not heading or not body:
            problems.append(f"slide {i}: missing heading or body")
            continue
        if len(heading.split()) > MAX_HEADING_WORDS:
            problems.append(f"slide {i}: heading over {MAX_HEADING_WORDS} words")
        if len(body.split()) > MAX_BODY_WORDS:
            problems.append(f"slide {i}: body over {MAX_BODY_WORDS} words "
                            f"({len(body.split())})")

        if not is_last:
            if not evidence_ok(evidence, source_norm):
                problems.append(f"slide {i}: evidence is not a word-for-word excerpt "
                                f"of the source: '{evidence[:80]}'")
        bad = numbers_ok(heading + " " + body, source_flat, source_words)
        if bad:
            problems.append(f"slide {i}: numbers not found in source: {bad}")

    caption = (data.get("caption") or "").strip()
    if not caption:
        problems.append("caption missing")
    elif "?" not in caption[-140:]:
        problems.append("caption must end with a question to the reader")
    else:
        bad = numbers_ok(caption, source_flat, source_words)
        if bad:
            problems.append(f"caption: numbers not found in source: {bad}")

    tags = data.get("specific_hashtags") or []
    if len(tags) != 5 or not all(re.fullmatch(r"#[a-z0-9]{3,30}", t) for t in tags):
        problems.append("specific_hashtags must be exactly 5 lowercase tags like #stoicism")

    if not problems:  # only render-test once the text itself is clean
        for i, s in enumerate(slides, start=1):
            body = s["body"].strip()
            if i == N_SLIDES and CTA_LINE not in body:
                body = f"{body}\n\n{CTA_LINE}"  # same thing build_item will do
            slide = {"heading": s["heading"].strip(), "body": body,
                     "kind": "hook" if i == 1 else "cta" if i == N_SLIDES else None}
            try:
                render_slide(slide, i, N_SLIDES)
            except ValueError as e:
                problems.append(str(e))
    return problems


# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------
def build_prompt(figure, source_text, feedback=None):
    prompt = f"""You write Instagram carousels for @rootedand.rich, an account for men aged \
18-34 in India and the US who care about money, discipline, and power. Voice: direct, blunt, \
talks TO the reader as "you", short sentences, zero fluff, no motivational-poster language. \
Specific beats abstract every time.

FIGURE: {figure['title']}
LANE: {figure.get('lane', 'money, discipline, power')}

HARD RULES (a script will check these and reject the draft if broken):
1. Use ONLY facts stated in the SOURCE text below. Never add anything from your own memory, \
not even things you are sure of. If the source doesn't say it, it doesn't go in.
2. Every slide except the last needs an "evidence" field: a WORD-FOR-WORD excerpt (6-30 words) \
copied exactly from the SOURCE that supports the slide's main fact. Do not paraphrase it. \
Do not stitch two passages together.
3. Every number, year, amount or percentage on a slide must appear in the SOURCE.
4. If the source hedges a claim (legend, "reportedly", "according to tradition", disputed), \
skip it or clearly say it is disputed.
5. Do not use famous quotes unless the SOURCE contains the quote with its attribution.
6. Heading: max {MAX_HEADING_WORDS} words. Body: max {MAX_BODY_WORDS} words. Use \\n for line breaks.

STRUCTURE ({N_SLIDES} slides):
- Slide 1: scroll-stopping hook. One surprising, specific fact stated as a bold claim.
- Slides 2-8: the story and the lesser-known specifics. One idea per slide. Prefer what most \
people DON'T know over what everyone knows. Include at least one failure, cost, or surprising \
detail, not just wins.
- Slide 9: what this means for the reader's money, discipline or power, grounded in the facts above.
- Slide 10: a closing line, then a genuine question to the reader, then the exact sentence: \
"{CTA_LINE}" (slide 10 evidence can be an empty string).

CAPTION: 2-3 sentences, same voice, must end with a question to the reader.
HASHTAGS: exactly 5 lowercase topic hashtags specific to this figure and theme \
(like #stoicism, #romanemperors). Do not include #rootedandrich.

Return ONLY this JSON, no markdown fences:
{{"angle": "one line on the angle you chose",
 "slides": [{{"heading": "...", "body": "...", "evidence": "..."}}],
 "caption": "...",
 "specific_hashtags": ["#a", "#b", "#c", "#d", "#e"]}}

SOURCE TEXT:
{source_text}
"""
    if feedback:
        prompt += ("\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED. Fix every one of these problems "
                   "and keep everything else:\n- " + "\n- ".join(feedback[:12]))
    return prompt


def call_gemini(prompt):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent")
    categories = ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                  "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6},
        "safetySettings": [{"category": c, "threshold": "BLOCK_ONLY_HIGH"} for c in categories],
    }
    resp = requests.post(url, params={"key": api_key}, json=body, timeout=120)
    if not resp.ok:
        print(f"Gemini HTTP {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    payload = resp.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        # Loud on purpose: silent safety-filter blocks hid failures before.
        raise RuntimeError(f"Gemini returned no candidates. "
                           f"promptFeedback={payload.get('promptFeedback')}")
    cand = candidates[0]
    parts = (cand.get("content") or {}).get("parts") or []
    if not parts:
        raise RuntimeError(f"Gemini returned empty content. finishReason={cand.get('finishReason')}")
    return json.loads(parts[0]["text"])


# --------------------------------------------------------------------------
# State, queue, output
# --------------------------------------------------------------------------
def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def pick_figures(forced_title=None):
    topics = load_json(TOPICS_FILE, {"figures": []})["figures"]
    state = load_json(STATE_FILE, {"done": [], "failures": {}})
    if forced_title:
        match = [f for f in topics if f["title"].lower() == forced_title.lower()]
        return [match[0] if match else {"title": forced_title}], state
    todo = [f for f in topics
            if f["title"] not in state["done"]
            and state["failures"].get(f["title"], 0) < MAX_FAILURES_BEFORE_SKIP]
    return todo, state


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")


def next_queue_number():
    nums = [int(m.group(1)) for p in QUEUE_DIR.glob("*.json")
            if (m := re.match(r"(\d+)_", p.name))]
    return (max(nums) if nums else 0) + 1


def build_item(figure, sources, data):
    slides = []
    for i, s in enumerate(data["slides"], start=1):
        body = s["body"].strip()
        if i == N_SLIDES and CTA_LINE not in body:
            body = f"{body}\n\n{CTA_LINE}"
        slides.append({
            "kind": "hook" if i == 1 else "cta" if i == N_SLIDES else "story",
            "heading": s["heading"].strip(),
            "body": body,
            "evidence": (s.get("evidence") or "").strip(),
        })
    src_line = "Source: " + "; ".join(x["title"] for x in sources[:2])
    hashtags = " ".join(data["specific_hashtags"]) + " #rootedandrich " + BROAD_HASHTAGS
    return {
        "id": slugify(figure["title"]),
        "figure": figure["title"],
        "angle": data.get("angle", ""),
        "caption": f"{data['caption'].strip()}\n\n{src_line}",
        "hashtags": hashtags,
        "sources": sources,
        "slides": slides,
    }


def write_review(item, filename):
    lines = [f"**{item['figure']}** is queued as `content/queue/{filename}` and will post "
             f"in queue order (Tue / Thu / Sun, 8 PM IST).", "",
             "**To cancel or edit it:** open that file on GitHub and delete or edit it "
             "before it posts. Doing nothing = it posts as-is.", "",
             f"Angle: {item['angle']}", "", "### Slides"]
    for i, s in enumerate(item["slides"], 1):
        lines += [f"**{i}. {s['heading']}**", s["body"].replace("\n", "  \n"), ""]
        if s["evidence"]:
            lines += [f"> evidence: {s['evidence']}", ""]
    lines += ["### Caption", item["caption"], "", item["hashtags"], "", "### Sources"]
    lines += [f"- {x['title']}: {x['url']}" for x in item["sources"]]
    REVIEW_FILE.write_text("\n".join(lines), encoding="utf-8")
    REVIEW_TITLE_FILE.write_text(f"Queued: {item['figure']}", encoding="utf-8")


def research_figure(figure):
    """Returns (item, problems_from_last_attempt)."""
    print(f"\n=== Researching: {figure['title']} ===")
    source_text, sources = gather_sources(figure)
    print(f"Source text: {len(source_text):,} characters")

    feedback = None
    for attempt in range(1, MAX_ATTEMPTS_PER_FIGURE + 1):
        print(f"Attempt {attempt}/{MAX_ATTEMPTS_PER_FIGURE}")
        try:
            data = call_gemini(build_prompt(figure, source_text, feedback))
        except Exception as e:
            feedback = [f"your last response could not be used: {e}"]
            print(f"  failed: {e}")
            continue
        problems = validate_draft(data, source_text)
        if not problems:
            item = build_item(figure, sources, data)
            validate(item)  # same checks the poster applies
            return item, []
        print("  rejected:\n   - " + "\n   - ".join(problems))
        feedback = problems
    return None, feedback or []


def main():
    dry_run = "--dry-run" in sys.argv
    forced = None
    if "--figure" in sys.argv:
        forced = sys.argv[sys.argv.index("--figure") + 1]

    figures, state = pick_figures(forced)
    if not figures:
        print("::error::No figures left in content/topics.json. Add more figures.")
        sys.exit(1)

    for figure in figures[:MAX_FIGURES_PER_RUN]:
        try:
            item, problems = research_figure(figure)
        except Exception as e:  # e.g. Wikipedia title not found
            item, problems = None, [str(e)]
            print(f"  could not research: {e}")

        if item is None:
            state["failures"][figure["title"]] = state["failures"].get(figure["title"], 0) + 1
            if not dry_run:
                STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
            continue

        if dry_run:
            print(json.dumps(item, indent=2, ensure_ascii=False))
            return

        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{next_queue_number():03d}_{item['id']}.json"
        (QUEUE_DIR / filename).write_text(
            json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")
        state["done"].append(figure["title"])
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        write_review(item, filename)
        print(f"\nQueued content/queue/{filename}")
        return

    print("::error::Could not produce a verified carousel for any figure this run. "
          "Nothing was queued.")
    sys.exit(1)


if __name__ == "__main__":
    main()
