"""
Offline tests for the fact-checking layer of research_carousel.py.
No network and no Gemini needed. Run from the repo root:

    python -m unittest discover -s tests -v
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import research_carousel as r  # noqa: E402

# Passages from Franklin's Autobiography (public domain), plus one line of
# fixture text so the numbers/years checks have something to find.
SOURCE = """
It was about this time I conceived the bold and arduous project of arriving at moral perfection.
Make no expense but to do good to others or yourself; i.e., waste nothing.
Lose no time; be always employed in something useful; cut off all unnecessary actions.
I determined to give a week's strict attention to each of the virtues successively.
Proceeding thus to the last, I could go through a course complete in thirteen weeks, and four courses in a year.
Frugality and Industry freeing me from my remaining debt, and producing affluence and independence.
My list of virtues contained at first but twelve; but a Quaker friend having kindly informed me that I was generally thought proud, I added Humility.
In truth, I found myself incorrigible with respect to Order; it cost me so much painful attention.
Though I never arrived at the perfection I had been so ambitious of obtaining, but fell far short of it, I was a better and a happier man.
In 1748, at the age of 42, Franklin retired from the printing business. He left 1,000 pounds to each city.
"""

EVIDENCE = [
    "Make no expense but to do good to others or yourself; i.e., waste nothing.",
    "I determined to give a week's strict attention to each of the virtues successively.",
    "I could go through a course complete in thirteen weeks, and four courses in a year.",
    "Frugality and Industry freeing me from my remaining debt, and producing affluence and independence",
    "My list of virtues contained at first but twelve; but a Quaker friend having kindly informed me",
    "I found myself incorrigible with respect to Order; it cost me so much painful attention.",
    "I never arrived at the perfection I had been so ambitious of obtaining, but fell far short of it",
    "In 1748, at the age of 42, Franklin retired from the printing business.",
    "Lose no time; be always employed in something useful; cut off all unnecessary actions.",
]


def good_draft():
    slides = []
    names = ["Hook", "Setup", "System", "Money", "Failure", "Order", "Twist", "Cost", "Lesson"]
    for i in range(9):
        slides.append({
            "heading": f"The {names[i]} slide",
            "body": "He tracked it every night. One week at a time.",
            "evidence": EVIDENCE[i],
        })
    slides[0]["body"] = "At 42, he walked away from the shop."          # 42 is in source
    slides[2]["body"] = "13 weeks per round. Four rounds a year."       # 'thirteen' in source
    slides.append({"heading": "His edge wasn't talent.",
                   "body": "It was tracking. What would you track for 13 weeks?",
                   "evidence": ""})
    return {
        "angle": "tracking system",
        "slides": slides,
        "caption": "He ran a system on himself. What would you track?",
        "specific_hashtags": ["#benjaminfranklin", "#habits", "#discipline",
                              "#historylessons", "#selfimprovement"],
    }


class ValidationTests(unittest.TestCase):
    def check(self, draft):
        return r.validate_draft(draft, SOURCE)

    def test_good_draft_passes(self):
        self.assertEqual(self.check(good_draft()), [])

    def test_fabricated_evidence_is_rejected(self):
        d = good_draft()
        d["slides"][3]["evidence"] = "He once refused a fortune offered by the king of France."
        problems = self.check(d)
        self.assertTrue(any("slide 4" in p and "evidence" in p for p in problems), problems)

    def test_paraphrased_evidence_is_rejected(self):
        d = good_draft()
        d["slides"][1]["evidence"] = "He decided to focus on one virtue every single week."
        self.assertTrue(any("slide 2" in p for p in self.check(d)))

    def test_too_short_evidence_is_rejected(self):
        d = good_draft()
        d["slides"][1]["evidence"] = "each of the virtues"
        self.assertTrue(any("slide 2" in p for p in self.check(d)))

    def test_invented_number_is_rejected(self):
        d = good_draft()
        d["slides"][4]["body"] = "He saved 5,000 pounds in his first year."
        problems = self.check(d)
        self.assertTrue(any("slide 5" in p and "numbers" in p for p in problems), problems)

    def test_number_in_source_as_digits_passes(self):
        d = good_draft()
        d["slides"][4]["body"] = "He left 1,000 pounds to each city."
        self.assertEqual(self.check(d), [])

    def test_number_in_source_as_words_passes(self):
        d = good_draft()
        d["slides"][4]["body"] = "Four rounds a year, 13 weeks each, 12 virtues at first."
        self.assertEqual(self.check(d), [])

    def test_invented_number_in_caption_is_rejected(self):
        d = good_draft()
        d["caption"] = "He earned 900 pounds a year. Would you?"
        self.assertTrue(any("caption" in p for p in self.check(d)))

    def test_caption_must_end_with_question(self):
        d = good_draft()
        d["caption"] = "He ran a system on himself."
        self.assertTrue(any("question" in p for p in self.check(d)))

    def test_wrong_slide_count(self):
        d = good_draft()
        d["slides"] = d["slides"][:8]
        self.assertTrue(any("exactly 10" in p for p in self.check(d)))

    def test_body_too_long(self):
        d = good_draft()
        d["slides"][5]["body"] = " ".join(["word"] * 60)
        self.assertTrue(any("slide 6" in p and "over" in p for p in self.check(d)))

    def test_bad_hashtags(self):
        d = good_draft()
        d["specific_hashtags"] = ["#ok", "no hash", "#a", "#b", "#c"]
        self.assertTrue(any("hashtags" in p for p in self.check(d)))

    def test_missing_body(self):
        d = good_draft()
        d["slides"][2]["body"] = ""
        self.assertTrue(any("slide 3" in p for p in self.check(d)))


class HelperTests(unittest.TestCase):
    def test_norm_ignores_case_punctuation_accents_and_curly_quotes(self):
        self.assertEqual(r.norm("Niccolò “The Prince” — 1532!"),
                         "niccolo the prince 1532")

    def test_word_numbers(self):
        found = r.word_numbers("thirteen weeks, forty-two years, two hundred men, "
                               "three thousand pounds, one million")
        for n in (13, 42, 200, 3000, 1000000):
            self.assertIn(n, found)

    def test_evidence_matches_across_punctuation_differences(self):
        src = r.norm("Make no expense but to do good to others or yourself; i.e., waste nothing.")
        self.assertTrue(r.evidence_ok("make no expense but to do good to others", src))

    def test_build_item_adds_cta_hashtags_and_source(self):
        item = r.build_item({"title": "Benjamin Franklin"},
                            [{"title": "Wikipedia: Benjamin Franklin", "url": "u"}],
                            good_draft())
        self.assertTrue(item["slides"][-1]["body"].endswith(r.CTA_LINE))
        self.assertEqual(len(item["hashtags"].split()), 11)
        self.assertIn("#rootedandrich", item["hashtags"])
        self.assertIn("Source: Wikipedia: Benjamin Franklin", item["caption"])
        self.assertEqual(item["slides"][0]["kind"], "hook")
        self.assertEqual(item["slides"][-1]["kind"], "cta")

    def test_item_passes_the_posters_own_validation(self):
        from carousel_reel import validate
        item = r.build_item({"title": "Benjamin Franklin"}, [{"title": "t", "url": "u"}],
                            good_draft())
        validate(item)  # raises if the poster would reject it


class QueueAndStateTests(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        Path("content/queue").mkdir(parents=True)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_queue_numbering_continues_after_existing_files(self):
        Path("content/queue/001_a.json").write_text("{}")
        Path("content/queue/007_b.json").write_text("{}")
        self.assertEqual(r.next_queue_number(), 8)

    def test_queue_numbering_starts_at_one(self):
        self.assertEqual(r.next_queue_number(), 1)

    def test_pick_skips_done_and_repeatedly_failed_figures(self):
        topics = {"figures": [{"title": "A"}, {"title": "B"}, {"title": "C"}]}
        Path("content/topics.json").write_text(json.dumps(topics))
        Path("content/research_state.json").write_text(
            json.dumps({"done": ["A"], "failures": {"B": 2}}))
        todo, _ = r.pick_figures()
        self.assertEqual([f["title"] for f in todo], ["C"])


if __name__ == "__main__":
    unittest.main()
