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
- Open with a real, specific opinion — try starters like "Here's the thing —", \
"Nobody tells you this, but —", "I used to think —", "Not gonna lie —", or just dive \
straight into the point like you're mid-conversation
- If a line sounds like it belongs on a motivational poster or in a textbook, rewrite \
it rougher, blunter, more personal. Specific beats abstract every time.
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
    """Try live AI generation first. Returns a post dict, or None on any failure."""
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

BLACK = "#0D0D0D"
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
    {"image_text": "Here's the thing about discipline \u2014\nit's not about the gym.\n\nEvery excuse you let slide,\nevery day you waste,\nyou're not just failing you.\n\nYou're wasting something you didn't even make.",
     "caption": "Show up like these days were handed to you on purpose. Because they were.\n\nWhat discipline are you actually rebuilding right now, not just posting about?",
     "hashtags": "#discipline #dailydiscipline #purposefulliving #stewardship #growthjourney #rootedandrich"},
    {"image_text": "Not gonna lie \u2014\nfear and faith can't both run your life.\n\nFear says hoard it, trust nobody.\nFaith says work hard, plan smart,\nand let go of what was never really yours.",
     "caption": "Most guys aren't broke because of money. They're broke because they don't trust the process they're actually building.\n\nWhich one's driving your decisions right now \u2014 fear or faith?",
     "hashtags": "#faithoverfear #trusttheprocess #moneymindset #spiritualgrowth #dailywisdom #rootedandrich"},
    {"image_text": "You want the better life?\nThen pay for it.\n\nNot with money \u2014\nwith early mornings,\nsaying no when yes is easier,\ngiving when it's tight,\nstudying when scrolling's easier.",
     "caption": "The guy you're praying to become is on the other side of these boring decisions. That's it. That's the whole secret.\n\nWhich one are you dodging right now?",
     "hashtags": "#disciplinequotes #paythecost #growthmindset #stewardship #dailywisdom #rootedandrich"},
    {"image_text": "Every paycheck you see?\nThat's proof somebody solved a problem\nyou haven't even tried yet.\n\nStop being mad about their win.\nStart studying how they got it.",
     "caption": "There's no shame in starting over. There's only shame in staying still because your pride won't let you begin.\n\nWho are you actually studying right now?",
     "hashtags": "#wealthmindset #levelup #financialwisdom #growthjourney #dailywisdom #rootedandrich"},
    {"image_text": "You were not designed to be ruled\nby impulses.\n\nEvery time you master a craving \u2014\nfood, spending, anger \u2014 you're practicing\ndominion over yourself.",
     "caption": "Self-control isn't restriction. It's the evidence that you belong to yourself again.\n\nWhat craving are you learning to master?",
     "hashtags": "#selfcontrol #discipline #innerstrength #stewardship #dailywisdom #rootedandrich"},
    {"image_text": "Debt is not a moral failure.\nBut denial is.\n\nTrack it. Name it. Attack it\nlike it owes you an apology.",
     "caption": "Freedom is boring before it's beautiful \u2014 budgets, spreadsheets, hard conversations. But a free man sleeps differently than a trapped one.\n\nWhat's the hard conversation you're avoiding?",
     "hashtags": "#debtfreejourney #financialwisdom #moneymindset #stewardship #dailydiscipline #rootedandrich"},
    {"image_text": "Never despise small beginnings.\n\nThe seed doesn't apologize\nfor not being a tree yet.",
     "caption": "Every empire you admire online started as someone's uncertain first year, in silence, with no proof it would work \u2014 except their obedience to the next small step.\n\nWhat's your small step today?",
     "hashtags": "#smallbeginnings #trusttheprocess #growthjourney #purposefulliving #dailywisdom #rootedandrich"},
    {"image_text": "Gratitude is the fastest way\nto unlock more.\n\nThose who were faithful with little\nwere trusted with much.",
     "caption": "Complaining about your current season keeps you stuck in it longer than you think.\n\nWhat are you grateful for in this season, even the hard parts?",
     "hashtags": "#gratitudepractice #stewardship #abundancemindset #dailywisdom #faithandfinance #rootedandrich"},
    {"image_text": "Protect your peace\nlike it's an inheritance.\nBecause it is.\n\nCut off the friend who only calls\nwhen they need something.\nLeave the room where your dreams\nget laughed at.",
     "caption": "Silence is not empty. It's where you hear what actually matters.\n\nWhat do you need to protect your peace from this month?",
     "hashtags": "#protectyourpeace #boundaries #mentalwealth #stewardship #dailywisdom #rootedandrich"},
    {"image_text": "Integrity is doing the right thing\nwith your money when no one's\nchecking your bank statement.\n\nWhat's built on integrity outlasts\nwhat's built on shortcuts.",
     "caption": "Pay people fairly. Keep your word on repayments. Don't build on other people's shortchanged trust.\n\nWho taught you integrity with money?",
     "hashtags": "#integritymatters #financialwisdom #stewardship #trustworthy #dailywisdom #rootedandrich"},
    {"image_text": "If you're rebuilding right now:\n\nBe relentless about your skills.\nGuard your reputation like your\nnet worth depends on it.\nGive generously even while growing.\nTrust the timeline you can't see yet.",
     "caption": "Your future self isn't impressed by your excuses. He's counting on your obedience today.\n\nWhat are you rebuilding this year?",
     "hashtags": "#rebuildingseason #growthjourney #disciplinequotes #purposefulliving #stewardship #rootedandrich"},
    {"image_text": "Everything you own,\nyou were trusted with \u2014\nnot entitled to.\n\nA wise steward doesn't grip.\nHe builds, gives, and stays ready\nto let go when asked.",
     "caption": "That reframes how you spend it, save it, and eventually pass it on.\n\nWhat has stewardship taught you?",
     "hashtags": "#stewardship #gratitude #wealthwisdom #purposefulliving #dailywisdom #rootedandrich"},
    {"image_text": "Prayer without a plan\nis just wishing.\n\nA plan without prayer\nis just pride.\n\nDo both.",
     "caption": "Work like it's all up to you. Trust like none of it ever was.\n\nWhich side do you lean on too much?",
     "hashtags": "#faithandwork #stewardship #purposefulliving #trusttheprocess #dailywisdom #rootedandrich"},
    {"image_text": "The most spiritually mature\nthing you can do this year\nmight be opening a savings account.\n\nFaith isn't the absence of\npractical wisdom.\nIt's often expressed through it.",
     "caption": "Small, boring, faithful decisions compound into a life you don't have to explain.\n\nWhat's your version of the savings account this year?",
     "hashtags": "#faithandfinance #savingsgoals #stewardship #practicalwisdom #dailywisdom #rootedandrich"},
    {"image_text": "Comparison is a tax on joy\nyou never agreed to pay.\n\nSomeone else's harvest was planted\nlong before you saw the fruit.\n\nStay in your own field.",
     "caption": "Study your own path more than you study someone else's highlight reel.\n\nWhat's growing in your field right now?",
     "hashtags": "#comparisonkillsjoy #staylane #gratitudepractice #mentalwealth #dailywisdom #rootedandrich"},
    {"image_text": "Rest is not the reward\nfor finishing.\n\nIt's the fuel\nfor starting again.",
     "caption": "Burnout isn't a badge of honor. It's a warning you ignored too long.\n\nWhen did you last actually rest, not just stop working?",
     "hashtags": "#restisproductive #burnoutrecovery #stewardship #dailywisdom #purposefulliving #rootedandrich"},
    {"image_text": "You will not regret the money\nyou gave away with a clear heart.\n\nYou will regret the money\nyou hoarded out of fear.",
     "caption": "Generosity isn't the enemy of wealth. Fear is.\n\nWho has your generosity shaped this year?",
     "hashtags": "#generosity #abundancemindset #stewardship #faithandfinance #dailywisdom #rootedandrich"},
    {"image_text": "Your word is worth more\nthan your bank balance.\n\nA man who breaks promises\ncan't be trusted with abundance.",
     "caption": "Character is the foundation wealth is built on top of, not the other way around.\n\nWhat's one promise you're keeping this month, even when it's inconvenient?",
     "hashtags": "#integritymatters #characterfirst #stewardship #trustworthy #dailywisdom #rootedandrich"},
    {"image_text": "Patience is not passive.\n\nIt's the discipline of staying\nobedient to the process\nwhile the results are still invisible.",
     "caption": "Most people quit in the gap between starting and seeing proof it's working.\n\nWhat are you being patient with right now?",
     "hashtags": "#patience #trusttheprocess #dailydiscipline #stewardship #growthjourney #rootedandrich"},
    {"image_text": "The tongue can build a legacy\nor burn one down\nin a single sentence.\n\nGuard it like it's part\nof your inheritance.",
     "caption": "Words spoken in anger cost more than money ever could.\n\nWhat's one word you're learning to hold back?",
     "hashtags": "#wordshavepower #wisdomforlife #stewardship #dailydiscipline #dailywisdom #rootedandrich"},
    {"image_text": "Simplicity is not poverty.\n\nIt's clarity about\nwhat actually matters\nonce the noise is removed.",
     "caption": "You don't need more things. You need fewer distractions from the right things.\n\nWhat could you simplify this month?",
     "hashtags": "#simplicityliving #minimalistmindset #stewardship #clarity #dailywisdom #rootedandrich"},
    {"image_text": "Sow in secret.\nHarvest in public.\n\nMost men want the harvest\nwithout ever doing\nthe planting no one saw.",
     "caption": "The work that builds real wealth is almost never the work people applaud.\n\nWhat are you planting in silence right now?",
     "hashtags": "#sowinsecret #consistencyiskey #stewardship #growthjourney #dailywisdom #rootedandrich"},
    {"image_text": "Envy convinces you\nsomeone else's blessing\nis your loss.\n\nIt was never a competition\nyou were entered into.",
     "caption": "Someone else's raise, promotion, or breakthrough was never subtracted from your own.\n\nWhose success are you learning to celebrate instead of resent?",
     "hashtags": "#letgoofenvy #celebrateothers #abundancemindset #stewardship #dailywisdom #rootedandrich"},
    {"image_text": "The wise man plans in seasons.\nThe foolish man reacts\nto moments.\n\nStop making permanent decisions\nfrom temporary emotions.",
     "caption": "Sleep on the big decision. Pray on the big decision. Then decide.\n\nWhat decision are you rushing right now?",
     "hashtags": "#wisdomforlife #dailydiscipline #stewardship #growthjourney #patternsofwisdom #rootedandrich"},
    {"image_text": "Your reputation is a currency\nyou can't print more of.\n\nSpend it carefully.\nProtect it fiercely.",
     "caption": "Trust takes years to build and a single choice to lose.\n\nWhat's one habit protecting your reputation right now?",
     "hashtags": "#reputationmatters #integrity #stewardship #trustworthy #dailywisdom #rootedandrich"},
    {"image_text": "Forgiveness is not\nletting someone off the hook.\n\nIt's taking yourself\noff their hook.",
     "caption": "Bitterness is the one debt that only costs you, never them.\n\nWho are you still holding a debt against that's really costing you?",
     "hashtags": "#forgivenessjourney #mentalwealth #freedomfrombitterness #stewardship #dailywisdom #rootedandrich"},
    {"image_text": "A budget is not\na cage for your money.\n\nIt's a leash you hold,\ninstead of one that holds you.",
     "caption": "Every rupee, every dollar, given a job before the month starts, stops fighting you by the end of it.\n\nDoes your money have a job this month?",
     "hashtags": "#budgetingtips #financialfreedom #moneymindset #stewardship #dailywisdom #rootedandrich"},
    {"image_text": "You were given exactly enough\nfor this season.\n\nThe complaint is rarely\nabout the amount.\nIt's about the comparison.",
     "caption": "Contentment isn't giving up ambition. It's refusing to let ambition steal your peace today.\n\nWhat are you grateful for in this exact season?",
     "hashtags": "#contentment #gratitudepractice #abundancemindset #stewardship #dailywisdom #rootedandrich"},
    {"image_text": "Legacy is not the money\nyou leave behind.\n\nIt's the character\nyou pass down\nthat knows what to do with it.",
     "caption": "Wealth without wisdom rarely survives a single generation.\n\nWhat wisdom are you passing down right now, to someone watching you?",
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

    left_margin = 90
    max_width = SIZE - (left_margin * 2)
    font_size = 38
    font = ImageFont.truetype(FONT_REG, font_size)
    line_height = int(font_size * 1.55)

    lines = wrap_and_measure(draw, image_text, font, max_width)

    # Fixed starting position — NOT based on this post's content length.
    # This is what keeps every post starting at the exact same height in
    # the grid, instead of short posts and long posts landing differently.
    start_y = int(SIZE * 0.30)

    y = start_y
    for line in lines:
        draw.text((left_margin, y), line, font=font, fill=WHITE)
        y += line_height

    font_small = ImageFont.truetype(FONT_REG, 26)
    draw.text((left_margin, SIZE - 90), HANDLE, font=font_small, fill=MUTED)

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
