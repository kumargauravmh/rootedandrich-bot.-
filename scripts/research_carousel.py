"""
research_carousel.py
---------------------
Researches the next subject in content/topics.json and writes a ready-to-post
one-frame reel into content/queue/ (the folder single_reel.py posts from).

A "subject" can be a real person, a fictional character, a book, a film or a
TV/anime/cartoon series. Anything with a genuine lesson about money,
discipline, power or faith that is worth sharing.

How it keeps facts honest (the whole point of this script):
  1. It downloads real source text: the subject's Wikipedia article, the
     article of the work it belongs to (for characters), and any extra
     public URLs you list for it (Project Gutenberg texts, Wikisource, etc.).
  2. Gemini may ONLY use that text, and must attach a word-for-word excerpt
     ("evidence") to every slide.
  3. Plain code (no AI) then checks that each excerpt really appears in the
     source and that every number on a slide appears in the source.
  4. Fiction and books get extra rules: the story must be named up front,
     everything is framed as "in the story" (never as real history), and
     long quotes from the work are rejected (copyright).
  5. A failed check rejects the whole draft; it retries with the error list
     (max 3 attempts per subject).

If nothing passes, NOTHING is queued and the run fails loudly (GitHub emails
you). There is no fallback content, by design.

It also finds new subjects by itself: when fewer than LOW_WATER unused
subjects remain in topics.json, Gemini proposes new ones and the script keeps
only those that exist as substantial Wikipedia articles.

Usage:
  python scripts/research_carousel.py                 # next subject, writes to queue
  python scripts/research_carousel.py --dry-run       # draft only, writes nothing
  python scripts/research_carousel.py --figure "Tyrion Lannister"
  python scripts/research_carousel.py --discover      # just add new subjects to topics.json

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

import random

from single_reel import QUEUE_DIR, load_state, render_single, validate_single  # same folder

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
LOW_WATER = 6            # discover new subjects when fewer than this many remain
DISCOVER_COUNT = 14      # how many candidates to ask Gemini for
MIN_ARTICLE_CHARS = 4000  # a candidate needs a substantial Wikipedia article

N_POINTS = 5
MIN_EVIDENCE_WORDS = 6   # keep in sync with the "6-30 words" instruction in the prompt
MAX_HOOK_WORDS = 12
MAX_POINT_WORDS = 18
MAX_CLOSER_WORDS = 14
MAX_QUOTE_WORDS_WORKS = 6  # longest quote allowed from a book/film/series
QUEUE_AHEAD = 3            # keep this many unposted carousels queued, no more

# Instagram does not expose live trending hashtags to any program, so these are
# high-volume tags in the niche, rotated per post (deterministically) for variety.
BROAD_POOL = ["#motivation", "#mindset", "#success", "#discipline", "#wealth", "#money",
              "#entrepreneur", "#selfimprovement", "#stoicism", "#millionairemindset",
              "#personalgrowth", "#wisdom", "#lifelessons", "#growthmindset",
              "#financialfreedom", "#businessmindset", "#inspiration", "#dailymotivation",
              "#history", "#hustle"]
REACH_POOL = ["#reels", "#reelsinstagram", "#viralreels", "#explorepage", "#fyp", "#trending"]

KINDS = {
    "person": "a real historical person",
    "fictional_character": "a fictional character",
    "book": "a book",
    "film": "a film",
    "series": "a TV, web, anime or cartoon series",
}
WORK_KINDS = {"fictional_character", "book", "film", "series"}  # not a real person


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
            "action": "query", "prop": "extracts|pageprops", "explaintext": 1,
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
    if "disambiguation" in (page.get("pageprops") or {}):
        raise ValueError(f"'{title}' is a disambiguation page on Wikipedia; use the exact "
                         f"article title, e.g. 'Name (film)'")
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

    # A character's own article is often thin; the work it belongs to is not.
    work = figure.get("work")
    if work:
        try:
            w_title, w_text, w_url = fetch_wikipedia(work)
            blocks.append(f"=== SOURCE {len(blocks) + 1}: Wikipedia, '{w_title}' ===\n{w_text}")
            sources.append({"title": f"Wikipedia: {w_title}", "url": w_url})
        except Exception as e:
            print(f"Skipping work article '{work}': {e}")

    for extra in figure.get("extra_sources", []):
        try:
            blocks.append(f"=== SOURCE {len(blocks) + 1}: {extra} ===\n{fetch_extra(extra)}")
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


def strip_parens(title):
    return re.sub(r"\s*\([^)]*\)", "", title).strip()


def long_quotes(text, max_words):
    """Quoted passages longer than max_words (straight or curly quotes)."""
    found = re.findall(r"[\"“]([^\"”]+)[\"”]", text)
    return [q for q in found if len(q.split()) > max_words]


def draft_texts(data):
    """Every piece of on-screen text, in reading order."""
    return ([data["hook"]["text"]] + [p["text"] for p in data["points"]] + [data["closer"]])


def validate_draft(data, source_text, figure=None):
    """Returns a list of problems. Empty list = the draft is acceptable."""
    problems = []
    kind = (figure or {}).get("kind", "person")
    source_norm = norm(source_text)
    source_flat = re.sub(r"(?<=\d),(?=\d)", "", source_text)
    source_words = word_numbers(source_text)

    hook = data.get("hook") or {}
    points = data.get("points")
    closer = (data.get("closer") or "").strip()
    if not isinstance(hook, dict) or not (hook.get("text") or "").strip():
        return ["missing hook"]
    if not isinstance(points, list) or len(points) != N_POINTS:
        return [f"need exactly {N_POINTS} points, got "
                f"{len(points) if isinstance(points, list) else 'none'}"]
    if not all(isinstance(p, dict) and (p.get("text") or "").strip() for p in points):
        return ["every point needs text"]
    if not closer:
        return ["missing closer"]

    # (label, text, evidence, word limit)
    parts = [("hook", hook["text"].strip(), (hook.get("evidence") or "").strip(), MAX_HOOK_WORDS)]
    for i, p in enumerate(points, 1):
        parts.append((f"point {i}", p["text"].strip(), (p.get("evidence") or "").strip(),
                      MAX_POINT_WORDS))

    for label, text, evidence, limit in parts:
        if len(text.split()) > limit:
            problems.append(f"{label}: over {limit} words ({len(text.split())})")
        if not evidence_ok(evidence, source_norm):
            problems.append(f"{label}: evidence is not a word-for-word excerpt of the "
                            f"source: '{evidence[:80]}'")
        bad = numbers_ok(text, source_flat, source_words)
        if bad:
            problems.append(f"{label}: numbers not found in source: {bad}")
        if kind in WORK_KINDS:
            for q in long_quotes(text, MAX_QUOTE_WORDS_WORKS):
                problems.append(f"{label}: quotes more than {MAX_QUOTE_WORDS_WORKS} words from "
                                f"the work; paraphrase instead: '{q[:60]}'")

    if hook["text"].strip().endswith("?"):
        problems.append("hook must be a bold statement of fact, not a question")

    if len(closer.split()) > MAX_CLOSER_WORDS:
        problems.append(f"closer: over {MAX_CLOSER_WORDS} words")
    if not closer.endswith("?"):
        problems.append("closer must be a question to the reader")
    bad = numbers_ok(closer, source_flat, source_words)
    if bad:
        problems.append(f"closer: numbers not found in source: {bad}")

    caption = (data.get("caption") or "").strip()
    if not caption:
        problems.append("caption missing")
    else:
        if "?" not in caption[-140:]:
            problems.append("caption must end with a question to the reader")
        if re.search(r"\b(wikipedia|sources?|according to)\b", caption, re.I):
            problems.append("caption must not mention sources or Wikipedia")
        if "#" in caption:
            problems.append("caption must not contain hashtags (they are added separately)")
        bad = numbers_ok(caption, source_flat, source_words)
        if bad:
            problems.append(f"caption: numbers not found in source: {bad}")
        if kind in WORK_KINDS:
            for q in long_quotes(caption, MAX_QUOTE_WORDS_WORKS):
                problems.append(f"caption: long quote from the work; paraphrase: '{q[:60]}'")

    tags = data.get("specific_hashtags") or []
    if len(tags) != 5 or not all(re.fullmatch(r"#[a-z0-9]{3,30}", t) for t in tags):
        problems.append("specific_hashtags must be exactly 5 lowercase tags like #stoicism")

    # Stories must be named up front so nobody mistakes fiction for history.
    if kind in WORK_KINDS and figure:
        opening = norm(" ".join([hook["text"], points[0]["text"], points[1]["text"]]))
        names = [strip_parens(figure["title"])]
        if figure.get("work"):
            names.append(strip_parens(figure["work"]))
        if not any(norm(n) and norm(n) in opening for n in names):
            problems.append("the hook or first two points must name the story/work "
                            f"({' or '.join(names)}) so readers know it is not real history")

    if not problems:  # only render-test once the text itself is clean
        try:
            render_single({"id": "fit-test", "caption": "x", "hashtags": "#x",
                           "hook": hook["text"].strip(),
                           "points": [p["text"].strip() for p in points],
                           "closer": closer})
        except ValueError as e:
            problems.append(str(e))
    return problems


# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------
def kind_rules(figure):
    kind = figure.get("kind", "person")
    if kind == "person":
        return ("This subject is a REAL PERSON. State facts as the source states them. "
                "Real quotes are allowed only if the SOURCE contains the quote with its attribution.")
    label = KINDS.get(kind, "a creative work")
    nonfiction = ("If the work is non-fiction, attribute every claim to the author "
                  "('the author argues...') and do not present the author's claims as proven fact. ")
    return (f"This subject is {label}. It is NOT a real person's life story.\n"
            "   - Name the story or book in the hook or the first two points (for example 'In The Godfather...').\n"
            "   - Frame every plot point as what happens IN the story, or what the creators, "
            "author or critics say. Never present fiction as real history.\n"
            f"   - {nonfiction}\n"
            f"   - The work is under copyright: PARAPHRASE. Do not quote dialogue, lines or "
            f"passages from it (max {MAX_QUOTE_WORDS_WORKS} words in quotation marks, only if the "
            "SOURCE contains them).\n"
            "   - The last point draws the real-life lesson, clearly labelled as the lesson for the reader.")


def build_prompt(figure, source_text, feedback=None):
    prompt = f"""You write ONE-FRAME Instagram Reels for @rootedand.rich, an account for men aged \
18-34 in India and the US who care about money, discipline, power and faith. The reel is a single \
still image with text: a hook, five points, and a closing question. No voiceover, no slides. \
Everything must be readable in about 15 seconds. Voice: direct, blunt, talks TO the reader as \
"you" where natural, short sentences, plain words, zero fluff, no motivational-poster language.

SUBJECT: {figure['title']}
KIND: {figure.get('kind', 'person')}
LANE: {figure.get('lane', 'money, discipline, power')}
{('ANGLE HINT: ' + figure['angle_hint']) if figure.get('angle_hint') else ''}

HARD RULES (a script will check these and reject the draft if broken):
1. Use ONLY facts stated in the SOURCE text below. Never add anything from your own memory, \
not even things you are sure of. If the source doesn't say it, it doesn't go in.
2. The hook and every point need an "evidence" field: a WORD-FOR-WORD excerpt (6-30 words) \
copied exactly from the SOURCE that supports it. Do not paraphrase it. Do not stitch two \
passages together.
3. Every number, year, amount or percentage you write must appear in the SOURCE.
4. If the source hedges a claim (legend, "reportedly", "according to tradition", disputed), \
skip it or clearly say it is disputed.
5. Length limits: hook max {MAX_HOOK_WORDS} words, each point max {MAX_POINT_WORDS} words, \
closer max {MAX_CLOSER_WORDS} words. The whole frame must fit on one screen, so be ruthless: \
keep only the FIVE most valuable facts out of everything in the source.
6. {kind_rules(figure)}

THE HOOK is everything. It decides whether anyone reads the rest. One sentence, a bold STATEMENT \
(never a question, never a title, never "The story of..."). It must contain one concrete, \
surprising, source-backed fact that creates a gap the viewer needs closed. Strong patterns:
   - an unexpected number or age: "[Who] did [surprising thing] at [number]."
   - a reversal: "[Who] had [everything], then [lost/gave it] because [specific reason]."
   - a hidden cost or paradox: "[Who] won by doing the thing everyone says to avoid."
   - a contradiction with common belief, only if the source supports it.
No clickbait the source cannot back up. Make it specific enough that it could only be about this subject.

THE FIVE POINTS: the most valuable, lesser-known facts, ordered as a mini-story with a turn. \
One fact per point. Prefer what most people DON'T know. Include at least one failure, cost or \
surprising detail, not only wins. Point 5 is the lesson for the reader's money, discipline, \
power or faith, grounded in the facts above.

THE CLOSER: one sharp question to the reader.

CAPTION: 2-3 sentences in the same voice that add ONE extra insight not already on the image, \
ending with a question. Do NOT mention sources, Wikipedia, or "according to". Do NOT include \
hashtags or emojis.
HASHTAGS: exactly 5 lowercase topic hashtags specific to this subject and theme \
(like #stoicism, #peakyblinders). Do not include #rootedandrich.

Return ONLY this JSON, no markdown fences:
{{"angle": "one line on the angle you chose",
 "hook": {{"text": "...", "evidence": "..."}},
 "points": [{{"text": "...", "evidence": "..."}}, {{"text": "...", "evidence": "..."}},
            {{"text": "...", "evidence": "..."}}, {{"text": "...", "evidence": "..."}},
            {{"text": "...", "evidence": "..."}}],
 "closer": "...",
 "caption": "...",
 "specific_hashtags": ["#a", "#b", "#c", "#d", "#e"]}}

SOURCE TEXT:
{source_text}
"""
    if feedback:
        prompt += ("\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED. Fix every one of these problems "
                   "and keep everything else:\n- " + "\n- ".join(feedback[:12]))
    return prompt


def call_gemini(prompt, temperature=0.6):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent")
    categories = ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                  "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": temperature},
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
# Finding new subjects by itself
# --------------------------------------------------------------------------
def discovery_prompt(existing_titles, n):
    return f"""You choose subjects for @rootedand.rich, an Instagram account for men aged 18-34 \
in India and the US about money, discipline, power and faith. One carousel is made per subject.

Propose {n} NEW subjects. A subject is worth it only if it has a genuine, specific lesson on money, \
discipline, power or faith that most people don't already know. Prefer lesser-known angles over \
the ten most famous names.

MIX (approximately):
- 5 real historical people from different eras and regions (at least 2 from outside Europe and \
the US: India, China, Africa, the Middle East, Latin America...)
- 3 fictional characters from films, TV, anime, cartoons, comics or novels
- 3 books (classic or modern, fiction or non-fiction)
- 3 films or series

RULES:
- "title" must be the EXACT English Wikipedia article title (include disambiguators such as \
"(film)" or "(TV series)" when Wikipedia does).
- kind is one of: person, fictional_character, book, film, series.
- For a fictional_character, give "work": the exact Wikipedia title of the film/series/book they \
come from.
- No living people. No politicians currently in office. No sacred religious figures. No real \
criminals or hate figures. Cautionary fictional characters are fine.
- Do not repeat any of these existing subjects: {json.dumps(sorted(existing_titles))[:3500]}

Return ONLY this JSON:
{{"candidates": [{{"title": "...", "kind": "person", "lane": "money|discipline|power|faith (or two joined by ' and ')", \
"work": "only for fictional_character", "why": "one line: the specific lesson"}}]}}"""


def wiki_check(title):
    """(resolved_title, article_length) or raises ValueError. Cheap existence test."""
    resolved, text, _ = fetch_wikipedia(title)
    return resolved, len(text)


def discover_topics(existing_titles, n=DISCOVER_COUNT):
    """Asks Gemini for candidates; keeps only real, substantial, non-duplicate
    Wikipedia articles. Returns the list of accepted topic dicts."""
    data = call_gemini(discovery_prompt(existing_titles, n), temperature=0.9)
    seen = {norm(t) for t in existing_titles}
    accepted = []
    for c in data.get("candidates", []):
        title, kind = (c.get("title") or "").strip(), (c.get("kind") or "").strip()
        if not title or kind not in KINDS:
            print(f"  skip (bad shape): {c}")
            continue
        try:
            resolved, length = wiki_check(title)
        except Exception as e:
            print(f"  skip '{title}': {e}")
            continue
        if length < MIN_ARTICLE_CHARS:
            print(f"  skip '{resolved}': article too short ({length} chars)")
            continue
        if norm(resolved) in seen:
            print(f"  skip '{resolved}': already in the list")
            continue
        entry = {"title": resolved, "kind": kind, "lane": c.get("lane", "money and discipline")}
        if kind == "fictional_character" and c.get("work"):
            entry["work"] = c["work"].strip()
        if c.get("why"):
            entry["angle_hint"] = c["why"].strip()
        seen.add(norm(resolved))
        accepted.append(entry)
        print(f"  + {resolved} ({kind})")
    return accepted


# --------------------------------------------------------------------------
# State, queue, output
# --------------------------------------------------------------------------
def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def unused_figures(topics, state):
    return [f for f in topics
            if f["title"] not in state["done"]
            and state["failures"].get(f["title"], 0) < MAX_FAILURES_BEFORE_SKIP]


def pick_figures(forced_title=None):
    topics = load_json(TOPICS_FILE, {"figures": []})["figures"]
    state = load_json(STATE_FILE, {"done": [], "failures": {}})
    if forced_title:
        match = [f for f in topics if f["title"].lower() == forced_title.lower()]
        return [match[0] if match else {"title": forced_title, "kind": "person"}], state
    return unused_figures(topics, state), state


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")


def next_queue_number():
    nums = [int(m.group(1)) for p in QUEUE_DIR.glob("*.json")
            if (m := re.match(r"(\d+)_", p.name))]
    return (max(nums) if nums else 0) + 1


def pick_hashtags(item_id, specific):
    """5 specific + 5 broad + 3 reach tags, rotated per post, + the brand tag."""
    rng = random.Random(item_id)
    broad = [t for t in BROAD_POOL if t not in specific]
    reach = list(REACH_POOL)
    return list(specific) + rng.sample(broad, 5) + rng.sample(reach, 3) + ["#rootedandrich"]


def build_item(figure, sources, data):
    item_id = slugify(figure["title"])
    return {
        "id": item_id,
        "figure": figure["title"],
        "kind": figure.get("kind", "person"),
        "angle": data.get("angle", ""),
        "hook": data["hook"]["text"].strip(),
        "points": [p["text"].strip() for p in data["points"]],
        "closer": data["closer"].strip(),
        "evidence": {"hook": (data["hook"].get("evidence") or "").strip(),
                     "points": [(p.get("evidence") or "").strip() for p in data["points"]]},
        "caption": data["caption"].strip(),   # no sources in the caption, by design
        "hashtags": " ".join(pick_hashtags(item_id, data["specific_hashtags"])),
        "sources": sources,                    # kept for YOUR review only
    }


def write_review(item, filename=None):
    where = (f"is queued as `content/queue/{filename}` and will post in queue order "
             f"(Sat / Sun / Mon / Wed / Fri, 8 PM IST)." if filename else
             "was drafted as a DRY RUN. Nothing was queued or saved.")
    lines = [f"## {item['figure']} ({item['kind']})", "", f"This {where}", ""]
    if filename:
        lines += ["**To cancel or edit it:** open that file on GitHub and delete or edit it "
                  "before it posts. Doing nothing = it posts as-is.", ""]
    ev = item["evidence"]
    lines += [f"Angle: {item['angle']}", "", "### On the reel",
              f"**HOOK:** {item['hook']}", f"> evidence: {ev['hook']}", ""]
    for i, (pt, e) in enumerate(zip(item["points"], ev["points"]), 1):
        lines += [f"**{i}.** {pt}", f"> evidence: {e}", ""]
    lines += [f"**CLOSER:** {item['closer']}", "", "### Caption", item["caption"], "",
              item["hashtags"], "", "### Sources (not shown to viewers)"]
    lines += [f"- {x['title']}: {x['url']}" for x in item["sources"]]
    REVIEW_FILE.write_text("\n".join(lines), encoding="utf-8")
    REVIEW_TITLE_FILE.write_text(f"Queued: {item['figure']}", encoding="utf-8")


def research_figure(figure):
    """Returns (item, problems_from_last_attempt)."""
    print(f"\n=== Researching: {figure['title']} ({figure.get('kind', 'person')}) ===")
    source_text, sources = gather_sources(figure)
    print(f"Source text: {len(source_text):,} characters from {len(sources)} source(s)")

    feedback = None
    for attempt in range(1, MAX_ATTEMPTS_PER_FIGURE + 1):
        print(f"Attempt {attempt}/{MAX_ATTEMPTS_PER_FIGURE}")
        try:
            data = call_gemini(build_prompt(figure, source_text, feedback))
        except Exception as e:
            feedback = [f"your last response could not be used: {e}"]
            print(f"  failed: {e}")
            continue
        problems = validate_draft(data, source_text, figure)
        if not problems:
            item = build_item(figure, sources, data)
            validate_single(item)  # same checks the poster applies
            return item, []
        print("  rejected:\n   - " + "\n   - ".join(problems))
        feedback = problems
    return None, feedback or []


def queue_ahead():
    """How many carousels are queued but not yet posted."""
    published = set(load_state().get("published", []))
    n = 0
    for path in QUEUE_DIR.glob("*.json"):
        item = json.loads(path.read_text(encoding="utf-8"))
        if item.get("id") not in published:
            n += 1
    return n


def top_up_topics(dry_run):
    """If the unused list is running low, ask for new subjects and save them."""
    topics_doc = load_json(TOPICS_FILE, {"figures": []})
    state = load_json(STATE_FILE, {"done": [], "failures": {}})
    remaining = len(unused_figures(topics_doc["figures"], state))
    if remaining >= LOW_WATER:
        return
    print(f"Only {remaining} unused subjects left; looking for new ones...")
    try:
        new = discover_topics([f["title"] for f in topics_doc["figures"]])
    except Exception as e:  # discovery is a bonus; never block today's research
        print(f"Discovery failed (continuing with what is in the list): {e}")
        return
    if new and not dry_run:
        topics_doc["figures"].extend(new)
        TOPICS_FILE.write_text(json.dumps(topics_doc, indent=2, ensure_ascii=False),
                               encoding="utf-8")
        print(f"Added {len(new)} new subjects to {TOPICS_FILE}")
    elif new:
        print(f"(dry run) would add {len(new)} new subjects")


def main():
    dry_run = "--dry-run" in sys.argv
    forced = None
    if "--figure" in sys.argv:
        forced = sys.argv[sys.argv.index("--figure") + 1]

    if "--discover" in sys.argv:
        topics_doc = load_json(TOPICS_FILE, {"figures": []})
        new = discover_topics([f["title"] for f in topics_doc["figures"]])
        if new and not dry_run:
            topics_doc["figures"].extend(new)
            TOPICS_FILE.write_text(json.dumps(topics_doc, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
        print(f"{'Would add' if dry_run else 'Added'} {len(new)} new subjects.")
        return

    # Self-regulating: this runs every day, but only adds one when the queue is running low.
    # (If GitHub skips a day, the queue still has a cushion.) Manual runs and dry runs skip this.
    if not forced and not dry_run and os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        ahead = queue_ahead()
        if ahead >= QUEUE_AHEAD:
            print(f"Queue already holds {ahead} unposted reels (cushion is {QUEUE_AHEAD}). "
                  f"Nothing to do today.")
            return

    if not forced:
        top_up_topics(dry_run)

    figures, state = pick_figures(forced)
    if not figures:
        print("::error::No subjects left in content/topics.json and discovery found none.")
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
            write_review(item)  # the workflow shows this on the run's summary page
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

    print("::error::Could not produce a verified carousel for any subject this run. "
          "Nothing was queued.")
    sys.exit(1)


if __name__ == "__main__":
    main()
