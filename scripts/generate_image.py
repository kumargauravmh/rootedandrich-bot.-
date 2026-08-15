"""
generate_image.py
------------------
PRIMARY: calls Google's free Gemini API to write a genuinely fresh post
every time it runs — new text, new caption, new hashtags, never repeated.

FALLBACK: if that call ever fails for any reason (no internet, rate limit,
bad response), it safely falls back to the next item in CONTENT_BANK below,
so a post always goes out either way.

Renders the result as a 1080x1080 black-background image for @rootedand.rich.
Runs automatically inside GitHub Actions, three times a day.
"""

import os
import json
import requests
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

GEMINI_MODEL = "gemini-2.5-flash-lite"

AI_PROMPT = """You write for @rootedand.rich — but you're not a quote generator. You're \
a guy who's actually wrestled with faith, discipline, and money, and you're talking \
straight to men aged 18-34 in India and the US who need to hear it like a real \
conversation, not a greeting card.

Voice rules — follow these closely:
- Talk directly TO the reader using "you" — never "men" in the abstract third person
- Sound like a real person thinking out loud: use contractions (don't, you're, it's), \
short punchy fragments, imperfect casual rhythm — NOT polished proverb sentences
- Open with a real scroll-stopping hook. Rotate between these patterns rather than \
always using the same one: a bold flat claim ("I guarantee you—"), a label ("TRUTH:", \
"FACT:", "REAL TALK:"), a direct address ("Stop doing this."), a myth-bust ("Nobody \
tells you this, but—"), or just dropping straight into the point mid-thought
- If a line sounds like it belongs on a motivational poster or in a textbook, rewrite \
it rougher, blunter, more specific. Specific beats abstract every time.
- It's fine to be direct or a little raw — this should read like real advice from an \
older brother or mentor, not a wisdom card
- Keep the faith and money themes, but ground them in something specific-sounding, \
not generic wisdom

Write ONE completely original Instagram post, different from anything written \
before, covering ONE of these themes (pick a different one each time): money \
stewardship, discipline, integrity, patience, gratitude, generosity, \
forgiveness, contentment, legacy, faith versus fear, protecting your peace, \
small beginnings, guarding your reputation, simplicity, or rest.

Return ONLY this exact JSON object, nothing else, no markdown fences:
{"image_text": "3-6 short lines using \\n for line breaks, sounding like real talk, \
not a polished quote", "caption": "1-3 sentences in the same direct voice, ending \
with a genuine question to the reader", "hashtags": "5-6 relevant hashtags separated \
by spaces, starting with #, always including #rootedandrich"}
"""


def generate_via_ai():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("No GEMINI_API_KEY set — skipping AI generation, using content bank.")
        return None

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={api_key}")
    body = {
        "contents": [{"parts": [{"text": AI_PROMPT}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.95},
    }

    try:
        resp = requests.post(url, json=body, timeout=30)
        resp.raise_for_status()
        raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        post = json.loads(raw_text)

        required = ["image_text", "caption", "hashtags"]
        if not all(k in post and post[k].strip() for k in required):
            print("AI response missing required fields — falling back to content bank.")
            return None

        print("Generated fresh content via Gemini AI.")
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

CONTENT_BANK = [
    {"image_text": "Nobody tells you this \u2014\nmoney's not the problem.\n\nYou worshipping what you earn?\nThat's the problem.",
     "caption": "Save before you spend. Give before you hoard. Walk away from anything promising too much too fast \u2014 every time.\n\nWhat's one money habit you're actually building this year, not just talking about?",
     "hashtags": "#moneywisdom #stewardship #wealthmindset #purposeoverprofit #dailywisdom #rootedandrich"},
    {"image_text": "Here's the thing about discipline \u2014\nit's not about the gym.\n\nEvery excuse you let slide,\nyou're not just failing you.\n\nYou're wasting something you didn't even make.",
     "caption": "Show up like these days were handed to you on purpose. Because they were.\n\nWhat discipline are you actually rebuilding right now, not just posting about?",
     "hashtags": "#discipline #dailydiscipline #purposefulliving #stewardship #growthjourney #rootedandrich"},
    {"image_text": "Not gonna lie \u2014\nfear and faith can't both run your life.\n\nFear says hoard it, trust nobody.\nFaith says work hard, plan smart,\nand let go of what was never really yours.",
     "caption": "Most guys aren't broke because of money. They're broke because they don't trust the process they're actually building.\n\nWhich one's driving your decisions right now \u2014 fear or faith?",
     "hashtags": "#faithoverfear #trusttheprocess #moneymindset #spiritualgrowth #dailywisdom #rootedandrich"},
    {"image_text": "You want the better life?\nThen pay for it.\n\nNot with money \u2014\nwith early mornings,\nsaying no when yes is easier,\nstudying when scrolling's easier.",
     "caption": "The guy you're praying to become is on the other side of these boring decisions. That's it. That's the whole secret.\n\nWhich one are you dodging right now?",
     "hashtags": "#disciplinequotes #paythecost #growthmindset #stewardship #dailywisdom #rootedandrich"},
    {"image_text": "Every paycheck you see?\nThat's proof somebody solved a problem\nyou haven't even tried yet.\n\nStop being mad about their win.\nStart studying how they got it.",
     "caption": "There's no shame in starting over. There's only shame in staying still because your pride won't let you begin.\n\nWho are you actually studying right now?",
     "hashtags": "#wealthmindset #levelup #financialwisdom #growthjourney #dailywisdom #rootedandrich"},
    {"image_text": "TRUTH:\n\nEvery time you master a craving \u2014\nfood, spending, anger \u2014\nyou're taking your power back.",
     "caption": "Self-control isn't restriction. It's proof you belong to yourself again.\n\nWhat craving are you learning to master?",
     "hashtags": "#selfcontrol #discipline #innerstrength #stewardship #dailywisdom #rootedandrich"},
    {"image_text": "Real talk \u2014\ndebt isn't a moral failure.\n\nDenial is.\n\nTrack it. Name it.\nAttack it like it owes you an apology.",
     "caption": "Freedom is boring before it's beautiful. But a free man sleeps different than a trapped one.\n\nWhat's the hard conversation you're avoiding?",
     "hashtags": "#debtfreejourney #financialwisdom #moneymindset #stewardship #dailydiscipline #rootedandrich"},
    {"image_text": "The seed never apologizes\nfor not being a tree yet.\n\nStop apologizing for yours.",
     "caption": "Every empire you admire started as someone's uncertain first year, in silence, with zero proof it'd work.\n\nWhat's your small step today?",
     "hashtags": "#smallbeginnings #trusttheprocess #growthjourney #purposefulliving #dailywisdom #rootedandrich"},
    {"image_text": "FACT:\n\nComplaining about this season\nkeeps you stuck in it\nlonger than you think.",
     "caption": "Those faithful with little get trusted with much. That's not a nice saying \u2014 it's just how it works.\n\nWhat are you actually grateful for right now?",
     "hashtags": "#gratitudepractice #stewardship #abundancemindset #dailywisdom #faithandfinance #rootedandrich"},
    {"image_text": "Cut the friend who only calls\nwhen they need something.\n\nLeave the room\nwhere your dreams get laughed at.\n\nYour peace is an inheritance.",
     "caption": "Silence isn't empty. It's where you finally hear what matters.\n\nWhat's draining your peace this month?",
     "hashtags": "#protectyourpeace #boundaries #mentalwealth #stewardship #dailywisdom #rootedandrich"},
    {"image_text": "Real integrity?\n\nIt's what you do with your money\nwhen nobody's checking\nyour bank statement.",
     "caption": "What's built on integrity outlasts what's built on shortcuts. Every time.\n\nWho taught you that?",
     "hashtags": "#integritymatters #financialwisdom #stewardship #trustworthy #dailywisdom #rootedandrich"},
    {"image_text": "If you're starting over right now \u2014\n\nget relentless about your skills.\nGuard your name like your future\ndepends on it. Because it does.",
     "caption": "Your future self isn't impressed by your excuses. He's counting on what you do today.\n\nWhat are you rebuilding this year?",
     "hashtags": "#rebuildingseason #growthjourney #disciplinequotes #purposefulliving #stewardship #rootedandrich"},
    {"image_text": "You don't actually own anything.\n\nYou were trusted with it.\n\nThat changes how you spend it,\nsave it, and let it go.",
     "caption": "A wise man builds, gives, and stays ready to release when it's time.\n\nWhat has stewardship taught you?",
     "hashtags": "#stewardship #gratitude #wealthwisdom #purposefulliving #dailywisdom #rootedandrich"},
    {"image_text": "Prayer without a plan\nis just wishing.\n\nA plan without prayer\nis just pride.\n\nDo both, brother.",
     "caption": "Work like it's all on you. Trust like none of it ever was.\n\nWhich side do you lean on too hard?",
     "hashtags": "#faithandwork #stewardship #purposefulliving #trusttheprocess #dailywisdom #rootedandrich"},
    {"image_text": "Not gonna lie \u2014\nthe most spiritual thing\nyou could do this year\nmight be opening a savings account.",
     "caption": "Faith isn't the opposite of practical. Sometimes it looks exactly like a budget.\n\nWhat's your version of that this year?",
     "hashtags": "#faithandfinance #savingsgoals #stewardship #practicalwisdom #dailywisdom #rootedandrich"},
    {"image_text": "Comparison is a tax\nyou never agreed to pay.\n\nStay in your own field.\nYour harvest is coming.",
     "caption": "Someone else's highlight reel isn't your timeline. Stop studying it like it is.\n\nWhat's actually growing in your life right now?",
     "hashtags": "#comparisonkillsjoy #staylane #gratitudepractice #mentalwealth #dailywisdom #rootedandrich"},
    {"image_text": "Rest isn't the reward\nfor finishing.\n\nIt's the fuel\nfor starting again.",
     "caption": "Burnout's not a badge of honor. It's a warning you ignored too long.\n\nWhen did you last actually rest, not just stop?",
     "hashtags": "#restisproductive #burnoutrecovery #stewardship #dailywisdom #purposefulliving #rootedandrich"},
    {"image_text": "You'll never regret\nthe money you gave\nwith a clear heart.\n\nYou'll regret every dollar\nyou hoarded out of fear.",
     "caption": "Generosity isn't wealth's enemy. Fear is.\n\nWho has your generosity shaped this year?",
     "hashtags": "#generosity #abundancemindset #stewardship #faithandfinance #dailywisdom #rootedandrich"},
    {"image_text": "Your word is worth more\nthan your bank balance.\n\nBreak promises,\nand no amount of money\nearns back trust.",
     "caption": "Character is the foundation wealth sits on \u2014 not the other way around.\n\nWhat promise are you keeping even when it's inconvenient?",
     "hashtags": "#integritymatters #characterfirst #stewardship #trustworthy #dailywisdom #rootedandrich"},
    {"image_text": "Patience isn't passive.\n\nIt's staying obedient to the process\nwhile the results\nare still invisible.",
     "caption": "Most guys quit in the gap between starting and seeing proof it's working.\n\nWhat are you being patient with right now?",
     "hashtags": "#patience #trusttheprocess #dailydiscipline #stewardship #growthjourney #rootedandrich"},
    {"image_text": "Your mouth can build a legacy\nor burn it down\nin one sentence.\n\nGuard it like your inheritance.",
     "caption": "Words said in anger cost more than money ever could.\n\nWhat's one thing you're learning to hold back?",
     "hashtags": "#wordshavepower #wisdomforlife #stewardship #dailydiscipline #dailywisdom #rootedandrich"},
    {"image_text": "Simplicity isn't poverty.\n\nIt's clarity \u2014\nonce you cut the noise out.",
     "caption": "You don't need more stuff. You need fewer distractions from what actually matters.\n\nWhat could you cut this month?",
     "hashtags": "#simplicityliving #minimalistmindset #stewardship #clarity #dailywisdom #rootedandrich"},
    {"image_text": "Everyone wants the harvest.\n\nNobody wants\nthe planting\nno one sees.",
     "caption": "Real wealth gets built in the work nobody claps for.\n\nWhat are you planting in silence right now?",
     "hashtags": "#sowinsecret #consistencyiskey #stewardship #growthjourney #dailywisdom #rootedandrich"},
    {"image_text": "Someone else's win\nwas never subtracted\nfrom yours.\n\nStop treating it like a competition\nyou got entered into.",
     "caption": "Their raise, their promotion, their breakthrough \u2014 none of it took anything from you.\n\nWhose win are you learning to actually celebrate?",
     "hashtags": "#letgoofenvy #celebrateothers #abundancemindset #stewardship #dailywisdom #rootedandrich"},
    {"image_text": "Don't make\na permanent decision\nfrom a temporary feeling.\n\nSleep on it. Pray on it.\nThen move.",
     "caption": "The wise plan in seasons. Everyone else just reacts to moments.\n\nWhat decision are you rushing right now?",
     "hashtags": "#wisdomforlife #dailydiscipline #stewardship #growthjourney #patternsofwisdom #rootedandrich"},
    {"image_text": "Your name is a currency\nyou can't print more of.\n\nSpend it careful.\nGuard it fierce.",
     "caption": "Trust takes years to build and one bad choice to burn down.\n\nWhat's protecting your name right now?",
     "hashtags": "#reputationmatters #integrity #stewardship #trustworthy #dailywisdom #rootedandrich"},
    {"image_text": "Forgiveness isn't\nletting them off the hook.\n\nIt's taking yourself\noff of theirs.",
     "caption": "Bitterness is the only debt that costs just you, never them.\n\nWho are you still paying interest on?",
     "hashtags": "#forgivenessjourney #mentalwealth #freedomfrombitterness #stewardship #dailywisdom #rootedandrich"},
    {"image_text": "A budget's not a cage.\n\nIt's a leash \u2014\nand you're the one holding it,\nnot the other way around.",
     "caption": "Give every dollar a job before the month starts, and it stops fighting you by the end of it.\n\nDoes your money have a job this month?",
     "hashtags": "#budgetingtips #financialfreedom #moneymindset #stewardship #dailywisdom #rootedandrich"},
    {"image_text": "You got exactly enough\nfor this season.\n\nThe complaint's rarely about the amount.\nIt's about who you're comparing to.",
     "caption": "Contentment isn't quitting on ambition. It's not letting ambition steal your peace today.\n\nWhat are you actually grateful for right now?",
     "hashtags": "#contentment #gratitudepractice #abundancemindset #stewardship #dailywisdom #rootedandrich"},
    {"image_text": "Legacy isn't the money\nyou leave behind.\n\nIt's the character\nyou hand down\nthat knows what to do with it.",
     "caption": "Wealth without wisdom rarely survives one generation.\n\nWhat are you actually passing down right now?",
     "hashtags": "#legacybuilding #generationalwisdom #stewardship #purposefulliving #dailywisdom #rootedandrich"},
]


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


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"last_index": -1}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


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

    image_path = f"posts/post_{slug}.png"
    caption_path = f"posts/caption_{slug}.txt"

    render_post(post["image_text"], image_path)

    full_caption = f"{post['caption']}\n\n.\n.\n.\n{post['hashtags']}"
    with open(caption_path, "w", encoding="utf-8") as f:
        f.write(full_caption)

    with open("posts/latest.txt", "w") as f:
        f.write(slug)

    print(f"Generated {image_path}")


if __name__ == "__main__":
    main()
