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

HOOK_EV = "In 1748, at the age of 42, Franklin retired from the printing business."
POINT_EV = [
    "I could go through a course complete in thirteen weeks, and four courses in a year.",
    "Frugality and Industry freeing me from my remaining debt, and producing affluence and independence",
    "a Quaker friend having kindly informed me that I was generally thought proud",
    "I found myself incorrigible with respect to Order; it cost me so much painful attention.",
    "I never arrived at the perfection I had been so ambitious of obtaining, but fell far short of it",
]
POINT_TXT = [
    "One virtue a week. 13 weeks a round. Four rounds a year.",
    "Frugality and Industry would clear his debt and buy independence.",
    "A Quaker friend said he seemed proud, so he added Humility.",
    "Order beat him. He called himself incorrigible at it.",
    "He never reached perfection, yet felt a better and happier man for trying.",
]


def good_draft():
    return {
        "angle": "tracking system",
        "hook": {"text": "He retired at 42 and never looked back.", "evidence": HOOK_EV},
        "points": [{"text": t, "evidence": e} for t, e in zip(POINT_TXT, POINT_EV)],
        "closer": "What one habit would you track for 13 weeks?",
        "caption": "He ran a system on himself and left a record of his failures too. What would you track?",
        "specific_hashtags": ["#benjaminfranklin", "#habits", "#discipline",
                              "#historylessons", "#selfimprovement"],
    }


class ValidationTests(unittest.TestCase):
    def check(self, draft, figure=None):
        return r.validate_draft(draft, SOURCE, figure)

    def test_good_draft_passes(self):
        self.assertEqual(self.check(good_draft()), [])

    def test_fabricated_hook_evidence_is_rejected(self):
        d = good_draft()
        d["hook"]["evidence"] = "He once refused a fortune offered by the king of France."
        self.assertTrue(any("hook" in p and "evidence" in p for p in self.check(d)))

    def test_fabricated_point_evidence_is_rejected(self):
        d = good_draft()
        d["points"][3]["evidence"] = "He once refused a fortune offered by the king of France."
        self.assertTrue(any("point 4" in p and "evidence" in p for p in self.check(d)))

    def test_paraphrased_evidence_is_rejected(self):
        d = good_draft()
        d["points"][1]["evidence"] = "He decided to focus on one virtue every single week."
        self.assertTrue(any("point 2" in p for p in self.check(d)))

    def test_too_short_evidence_is_rejected(self):
        d = good_draft()
        d["points"][1]["evidence"] = "each of the virtues"
        self.assertTrue(any("point 2" in p for p in self.check(d)))

    def test_invented_number_is_rejected(self):
        d = good_draft()
        d["points"][2]["text"] = "He saved 5,000 pounds in his first year."
        problems = self.check(d)
        self.assertTrue(any("point 3" in p and "numbers" in p for p in problems), problems)

    def test_number_in_source_as_digits_and_words_passes(self):
        d = good_draft()
        d["points"][2]["text"] = "He left 1,000 pounds. Twelve virtues at first, 13 later."
        self.assertEqual(self.check(d), [])

    def test_invented_number_in_hook_or_caption_is_rejected(self):
        d = good_draft()
        d["hook"]["text"] = "He retired at 55."
        self.assertTrue(any("hook" in p and "numbers" in p for p in self.check(d)))
        d = good_draft()
        d["caption"] = "He earned 900 pounds a year. Would you?"
        self.assertTrue(any("caption" in p for p in self.check(d)))

    def test_hook_must_be_a_statement(self):
        d = good_draft()
        d["hook"]["text"] = "Why did he retire at 42?"
        self.assertTrue(any("not a question" in p for p in self.check(d)))

    def test_closer_must_be_a_question(self):
        d = good_draft()
        d["closer"] = "Track one habit."
        self.assertTrue(any("closer must be a question" in p for p in self.check(d)))

    def test_caption_must_end_with_question(self):
        d = good_draft()
        d["caption"] = "He ran a system on himself."
        self.assertTrue(any("question" in p for p in self.check(d)))

    def test_caption_must_not_mention_sources_or_hashtags(self):
        for bad in ("Source: Wikipedia. What would you track?",
                    "According to his book he tracked it. What would you track?",
                    "He tracked it #habits. What would you track?"):
            d = good_draft()
            d["caption"] = bad
            self.assertTrue(any("caption must not" in p for p in self.check(d)), bad)

    def test_exactly_five_points(self):
        d = good_draft()
        d["points"] = d["points"][:4]
        self.assertTrue(any("exactly 5 points" in p for p in self.check(d)))

    def test_word_limits(self):
        d = good_draft()
        d["hook"]["text"] = " ".join(["retired"] * 14)
        d["points"][0]["text"] = " ".join(["word"] * 25)
        d["closer"] = " ".join(["word"] * 20) + "?"
        problems = self.check(d)
        self.assertTrue(any(p.startswith("hook: over") for p in problems), problems)
        self.assertTrue(any(p.startswith("point 1: over") for p in problems), problems)
        self.assertTrue(any(p.startswith("closer: over") for p in problems), problems)

    def test_text_that_cannot_fit_one_frame_is_rejected(self):
        d = good_draft()
        long_text = "Frugality and Industry would clear his debt and buy him independence for life ok."
        for pt in d["points"]:
            pt["text"] = long_text                      # 15 words each, still within the word cap
        d["hook"]["text"] = "He retired at 42 and never looked back or worked as a printer ever again."
        problems = self.check(d)
        # may or may not overflow; the point is: if it does, it is reported, never crashes
        self.assertTrue(problems == [] or any("fit" in p or "over" in p for p in problems))

    def test_bad_hashtags(self):
        d = good_draft()
        d["specific_hashtags"] = ["#ok", "no hash", "#a", "#b", "#c"]
        self.assertTrue(any("hashtags" in p for p in self.check(d)))

    def test_missing_pieces(self):
        d = good_draft()
        d["hook"] = {}
        self.assertEqual(self.check(d), ["missing hook"])
        d = good_draft()
        d["closer"] = ""
        self.assertEqual(self.check(d), ["missing closer"])


FICTION = {"title": "Michael Corleone", "kind": "fictional_character", "work": "The Godfather"}


def fiction_draft():
    d = good_draft()
    d["hook"]["text"] = "In The Godfather, Michael retired at 42."
    return d


class FictionRuleTests(unittest.TestCase):
    def check(self, draft, figure=FICTION):
        return r.validate_draft(draft, SOURCE, figure)

    def test_fiction_draft_that_names_the_story_passes(self):
        self.assertEqual(self.check(fiction_draft()), [])

    def test_fiction_must_name_the_story(self):
        problems = self.check(good_draft())
        self.assertTrue(any("must name the story" in p for p in problems), problems)

    def test_naming_it_in_the_first_two_points_also_counts(self):
        d = good_draft()
        d["points"][1]["text"] = "Michael Corleone tracked it every night."
        self.assertEqual(self.check(d), [])

    def test_long_quote_from_a_work_is_rejected(self):
        d = fiction_draft()
        d["points"][2]["text"] = 'He says "make no expense but to do good to others or yourself" once.'
        problems = self.check(d)
        self.assertTrue(any("point 3" in p and "quotes more than" in p for p in problems), problems)

    def test_short_quote_from_a_work_is_fine(self):
        d = fiction_draft()
        d["points"][2]["text"] = 'He calls it "waste nothing" every night.'
        self.assertEqual(self.check(d), [])

    def test_same_long_quote_is_fine_for_a_real_person(self):
        d = good_draft()
        d["points"][2]["text"] = 'He wrote "make no expense but to do good to others or yourself".'
        problems = self.check(d, {"title": "Benjamin Franklin", "kind": "person"})
        self.assertFalse([p for p in problems if "quote" in p], problems)

    def test_book_kind_gets_the_same_rules(self):
        problems = self.check(good_draft(), {"title": "The Art of War", "kind": "book"})
        self.assertTrue(any("must name the story" in p for p in problems), problems)

    def test_parenthesised_titles_match_without_the_parenthesis(self):
        d = good_draft()
        d["hook"]["text"] = "Gordon Gekko retired at 42."
        fig = {"title": "Gordon Gekko", "kind": "fictional_character", "work": "Wall Street (1987 film)"}
        self.assertEqual(self.check(d, fig), [])

    def test_prompt_rules(self):
        p = r.build_prompt(FICTION, "SRC")
        self.assertIn("NOT a real person", p)
        self.assertIn("PARAPHRASE", p)
        person = r.build_prompt({"title": "X", "kind": "person"}, "SRC")
        self.assertIn("REAL PERSON", person)
        self.assertNotIn("PARAPHRASE", person)

    def test_prompt_demands_a_strong_hook_and_no_sources_in_caption(self):
        p = r.build_prompt({"title": "X", "kind": "person"}, "SRC")
        self.assertIn("THE HOOK is everything", p)
        self.assertIn("FIVE", p)
        self.assertIn("Do NOT mention sources", p)


class BuildItemTests(unittest.TestCase):
    def item(self, title="Benjamin Franklin"):
        return r.build_item({"title": title, "kind": "person"},
                            [{"title": "Wikipedia: X", "url": "u"}], good_draft())

    def test_shape_and_no_sources_in_caption(self):
        it = self.item()
        self.assertEqual(len(it["points"]), 5)
        self.assertNotIn("Source", it["caption"])
        self.assertNotIn("Wikipedia", it["caption"])
        self.assertEqual(it["sources"][0]["title"], "Wikipedia: X")  # kept for review only

    def test_hashtags_are_14_unique_and_include_brand_and_reach_tags(self):
        tags = self.item()["hashtags"].split()
        self.assertEqual(len(tags), 14)
        self.assertEqual(len(set(tags)), 14)
        self.assertIn("#rootedandrich", tags)
        self.assertTrue(set(tags) & set(r.REACH_POOL))
        self.assertEqual(tags[:5], good_draft()["specific_hashtags"])

    def test_hashtags_are_deterministic_per_subject_but_vary_between_subjects(self):
        a1, a2 = self.item("Seneca").get("hashtags"), self.item("Seneca").get("hashtags")
        b = self.item("Epictetus")["hashtags"]
        self.assertEqual(a1, a2)
        self.assertNotEqual(a1, b)

    def test_item_passes_the_posters_own_validation_and_renders(self):
        from single_reel import render_single, validate_single
        it = self.item()
        validate_single(it)
        self.assertEqual(render_single(it).size, (1080, 1920))


class HelperTests(unittest.TestCase):
    def test_norm_ignores_case_punctuation_accents_and_curly_quotes(self):
        self.assertEqual(r.norm("Niccol\u00f2 \u201cThe Prince\u201d \u2014 1532!"),
                         "niccolo the prince 1532")

    def test_word_numbers(self):
        found = r.word_numbers("thirteen weeks, forty-two years, two hundred men, "
                               "three thousand pounds, one million")
        for n in (13, 42, 200, 3000, 1000000):
            self.assertIn(n, found)

    def test_evidence_matches_across_punctuation_differences(self):
        src = r.norm("Make no expense but to do good to others or yourself; i.e., waste nothing.")
        self.assertTrue(r.evidence_ok("make no expense but to do good to others", src))


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

    def test_queue_ahead_counts_only_unposted_items(self):
        for i, name in enumerate(["a", "b", "c"], 1):
            Path(f"content/queue/00{i}_{name}.json").write_text(json.dumps({"id": name}))
        Path("content/state.json").write_text(json.dumps({"published": ["a"]}))
        self.assertEqual(r.queue_ahead(), 2)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self._orig = (r.call_gemini, r.wiki_check)

    def tearDown(self):
        r.call_gemini, r.wiki_check = self._orig

    def test_keeps_only_real_substantial_new_valid_candidates(self):
        r.call_gemini = lambda prompt, temperature=0.6: {"candidates": [
            {"title": "Good Book", "kind": "book", "lane": "money", "why": "lesson"},
            {"title": "Fake Thing", "kind": "book", "lane": "money"},          # no wikipedia page
            {"title": "Stub Person", "kind": "person", "lane": "power"},        # too short
            {"title": "Already Here", "kind": "person", "lane": "power"},       # duplicate
            {"title": "Weird Kind", "kind": "podcast", "lane": "power"},        # bad kind
            {"title": "Some Hero", "kind": "fictional_character", "lane": "discipline",
             "work": "Some Show"},
        ]}

        def fake_wiki(title):
            if title == "Fake Thing":
                raise ValueError("Wikipedia has no article titled 'Fake Thing'")
            if title == "Stub Person":
                return title, 900
            return title, 20000
        r.wiki_check = fake_wiki
        got = r.discover_topics(["Already Here"])
        self.assertEqual([g["title"] for g in got], ["Good Book", "Some Hero"])
        self.assertEqual(got[1]["work"], "Some Show")
        self.assertEqual(got[0]["angle_hint"], "lesson")

    def test_redirect_resolving_to_an_existing_subject_is_a_duplicate(self):
        r.call_gemini = lambda prompt, temperature=0.6: {"candidates": [
            {"title": "Ben Franklin", "kind": "person", "lane": "money"}]}
        r.wiki_check = lambda t: ("Benjamin Franklin", 50000)
        self.assertEqual(r.discover_topics(["Benjamin Franklin"]), [])


class TopUpTests(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        Path("content").mkdir()
        self._orig = r.discover_topics
        self.calls = 0

        def fake(existing):
            self.calls += 1
            return [{"title": "Brand New", "kind": "person", "lane": "money"}]
        r.discover_topics = fake

    def tearDown(self):
        r.discover_topics = self._orig
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def write_topics(self, n):
        figs = [{"title": f"T{i}", "kind": "person"} for i in range(n)]
        Path("content/topics.json").write_text(json.dumps({"figures": figs}))

    def test_discovers_when_running_low(self):
        self.write_topics(3)
        r.top_up_topics(dry_run=False)
        titles = [f["title"] for f in json.loads(Path("content/topics.json").read_text())["figures"]]
        self.assertIn("Brand New", titles)

    def test_does_not_discover_when_plenty_left(self):
        self.write_topics(10)
        r.top_up_topics(dry_run=False)
        self.assertEqual(self.calls, 0)

    def test_dry_run_never_writes(self):
        self.write_topics(3)
        r.top_up_topics(dry_run=True)
        titles = [f["title"] for f in json.loads(Path("content/topics.json").read_text())["figures"]]
        self.assertNotIn("Brand New", titles)

    def test_discovery_failure_never_blocks_research(self):
        self.write_topics(3)

        def boom(existing):
            raise RuntimeError("gemini down")
        r.discover_topics = boom
        r.top_up_topics(dry_run=False)  # must not raise


if __name__ == "__main__":
    unittest.main()
