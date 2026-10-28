import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import slot  # noqa: E402

IST = slot.IST


def at(day, hh, mm=0):
    """2026-10-DD in IST. Oct 28 2026 is a Wednesday."""
    return datetime(2026, 10, day, hh, mm, tzinfo=IST)


class DecideTests(unittest.TestCase):
    def test_posting_days_are_sat_sun_mon_wed_fri(self):
        # Oct 26 Mon, 27 Tue, 28 Wed, 29 Thu, 30 Fri, 31 Sat, Nov 1 Sun
        ok = {26: True, 27: False, 28: True, 29: False, 30: True, 31: True}
        for day, expected in ok.items():
            got, _ = slot.decide(at(day, 17), "schedule", None)
            self.assertEqual(got, expected, f"Oct {day}")
        self.assertTrue(slot.decide(datetime(2026, 11, 1, 17, tzinfo=IST), "schedule", None)[0])

    def test_waits_when_in_the_window(self):
        ok, why = slot.decide(at(28, 17), "schedule", None)
        self.assertTrue(ok)
        self.assertIn("180 min", why)

    def test_skips_when_too_early_for_the_6_hour_job_limit(self):
        ok, why = slot.decide(at(28, 12), "schedule", None)   # 8h to go
        self.assertFalse(ok)
        self.assertIn("too early", why)

    def test_edge_exactly_at_the_wait_cap_proceeds(self):
        self.assertTrue(slot.decide(at(28, 14, 30), "schedule", None)[0])   # 330 min
        self.assertFalse(slot.decide(at(28, 14, 29), "schedule", None)[0])  # 331 min

    def test_late_run_posts_immediately_like_last_tuesday(self):
        ok, why = slot.decide(at(28, 1, 0).replace(day=28, hour=23, minute=0), "schedule", None)
        self.assertTrue(ok)
        self.assertIn("past 8:00 PM", why)

    def test_never_twice_in_one_ist_day(self):
        ok, why = slot.decide(at(28, 17), "schedule", "2026-10-28")
        self.assertFalse(ok)
        self.assertIn("already posted", why)

    def test_yesterdays_post_does_not_block_today(self):
        self.assertTrue(slot.decide(at(28, 17), "schedule", "2026-10-26")[0])

    def test_manual_runs_always_proceed_even_on_off_days_and_after_posting(self):
        for event in ("workflow_dispatch",):
            self.assertTrue(slot.decide(at(27, 3), event, "2026-10-27")[0])


class WaitMathTests(unittest.TestCase):
    def test_seconds_until_slot(self):
        self.assertEqual(slot.seconds_until_slot(at(28, 19)), 3600)
        self.assertEqual(slot.seconds_until_slot(at(28, 20)), 0)
        self.assertEqual(slot.seconds_until_slot(at(28, 22)), 0)

    def test_target_is_8pm_ist_which_is_1430_utc(self):
        from datetime import timezone
        t = slot.target_for(at(28, 9)).astimezone(timezone.utc)
        self.assertEqual((t.hour, t.minute), (14, 30))


if __name__ == "__main__":
    unittest.main()
