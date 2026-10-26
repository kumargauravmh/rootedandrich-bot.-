import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import token_watch as tw  # noqa: E402

CFG = {"ig_token_issued": "2026-10-26", "ig_token_lifetime_days": 60,
       "warn_days_before": 10, "media_warn_days_before": 14}
TODAY0 = date(2026, 10, 26)


def titles(problems):
    return [t for t, _ in problems]


class DaysLeftTests(unittest.TestCase):
    def test_fresh_token_has_60_days(self):
        self.assertEqual(tw.days_left_ig("2026-10-26", TODAY0, 60), 60)

    def test_counts_down(self):
        self.assertEqual(tw.days_left_ig("2026-10-26", date(2026, 12, 15), 60), 10)

    def test_goes_negative_after_expiry(self):
        self.assertLess(tw.days_left_ig("2026-10-26", date(2027, 1, 1), 60), 0)


class HeaderTests(unittest.TestCase):
    def test_parses_github_format(self):
        self.assertEqual(tw.parse_expiry_header("2026-11-24 00:00:00 UTC"), date(2026, 11, 24))

    def test_missing_or_garbage_is_none(self):
        self.assertIsNone(tw.parse_expiry_header(None))
        self.assertIsNone(tw.parse_expiry_header("never"))


class EvaluateTests(unittest.TestCase):
    def run_eval(self, today, ig_err=None, media="ok", media_exp=None):
        return tw.evaluate(CFG, today, ig_err, media, media_exp, "o/media")

    def test_all_fine_is_silent(self):
        self.assertEqual(self.run_eval(date(2026, 11, 20), media_exp=date(2027, 6, 1)), [])

    def test_warns_ten_days_before_instagram_expiry(self):
        self.assertEqual(self.run_eval(date(2026, 12, 14)), [])             # 11 days left
        got = self.run_eval(date(2026, 12, 15))                              # 10 days left
        self.assertEqual(len(got), 1)
        self.assertIn("expires in about 10 days", got[0][0])

    def test_warns_after_instagram_life_has_passed(self):
        got = self.run_eval(date(2027, 1, 5))
        self.assertIn("passed its 60-day life", got[0][0])

    def test_live_failure_beats_the_date_estimate(self):
        got = self.run_eval(date(2026, 10, 27), ig_err="Meta error 190: expired")
        self.assertEqual(titles(got), ["Instagram token is NOT working"])
        self.assertIn("Generate token", got[0][1])

    def test_media_token_expiring_soon(self):
        got = self.run_eval(date(2026, 11, 1), media_exp=date(2026, 11, 10))
        self.assertIn("Media repo token expires in 9 days", got[0][0])

    def test_media_token_far_from_expiry_is_silent(self):
        self.assertEqual(self.run_eval(date(2026, 11, 1), media_exp=date(2027, 1, 1)), [])

    def test_media_token_dead(self):
        got = self.run_eval(date(2026, 11, 1), media="GitHub answered 401")
        self.assertEqual(titles(got), ["Media repo token is NOT working"])
        self.assertIn("o/media", got[0][1])

    def test_both_problems_reported_together(self):
        got = self.run_eval(date(2026, 12, 20), media="GitHub answered 404")
        self.assertEqual(len(got), 2)


if __name__ == "__main__":
    unittest.main()
