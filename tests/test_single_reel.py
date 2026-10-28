import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import single_reel as sr  # noqa: E402

ITEM = {
    "id": "x", "caption": "cap", "hashtags": "#a #b",
    "hook": "He retired at 42 with a two-page contract and never worked again.",
    "points": ["One virtue a week. Thirteen weeks a round. Four rounds a year.",
               "Frugality and Industry would clear his debt and buy independence.",
               "A Quaker friend said he seemed proud, so he added Humility.",
               "Order beat him. He called himself incorrigible at it.",
               "He never reached perfection, yet felt a better and happier man for trying."],
    "closer": "What one habit would you track for thirteen weeks?",
}


class RenderTests(unittest.TestCase):
    def test_frame_is_1080x1920(self):
        self.assertEqual(sr.render_single(ITEM).size, (1080, 1920))

    def test_nothing_is_drawn_outside_the_reels_safe_area(self):
        img = sr.render_single(ITEM)
        px = img.convert("L").point(lambda v: 255 if v > 12 else 0)
        left, top, right, bottom = px.getbbox()
        self.assertGreaterEqual(top, sr.SAFE_TOP - 5, "text intrudes into the top UI zone")
        self.assertLessEqual(bottom, sr.SAFE_BOTTOM + 5, "text intrudes into the bottom UI zone")
        self.assertGreaterEqual(left, sr.LEFT - 5)
        self.assertLessEqual(right, sr.W - sr.RIGHT_MARGIN + 5, "text runs under the side buttons")

    def test_hook_is_gold_and_points_are_white(self):
        img = sr.render_single(ITEM)
        colours = {c for _, c in img.getcolors(maxcolors=1_000_000) if sum(c) > 150}
        self.assertTrue(any(c[0] > 180 and c[2] < 120 for c in colours), "no gold pixels")
        self.assertTrue(any(min(c) > 200 for c in colours), "no white pixels")

    def test_oversized_text_is_rejected_not_clipped(self):
        big = dict(ITEM, points=["word " * 60] * 5)
        with self.assertRaises(ValueError):
            sr.render_single(big)

    def test_missing_or_wrong_number_of_points_is_rejected(self):
        with self.assertRaises(ValueError):
            sr.render_single(dict(ITEM, points=ITEM["points"][:4]))
        with self.assertRaises(ValueError):
            sr.render_single({k: v for k, v in ITEM.items() if k != "hook"})


class TimingTests(unittest.TestCase):
    def test_duration_is_clamped(self):
        short = dict(ITEM, hook="Hi.", points=["a"] * 5, closer="Ok?")
        self.assertEqual(sr.single_seconds(short), sr.MIN_SECONDS)
        self.assertLessEqual(sr.single_seconds(ITEM), sr.MAX_SECONDS)
        self.assertGreaterEqual(sr.single_seconds(ITEM), sr.MIN_SECONDS)


class VideoTests(unittest.TestCase):
    def test_builds_a_silent_vertical_h264_reel_of_the_right_length(self):
        with tempfile.TemporaryDirectory() as d:
            frame = Path(d) / "f.png"
            sr.render_single(ITEM).save(frame)
            out = Path(d) / "r.mp4"
            sr.build_video(frame, 12, out)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height",
                 "-show_entries", "format=duration", "-of", "json", str(out)],
                capture_output=True, text=True, check=True)
            info = json.loads(probe.stdout)
            streams = {s["codec_name"]: s for s in info["streams"]}
            self.assertEqual((streams["h264"]["width"], streams["h264"]["height"]), (1080, 1920))
            self.assertIn("aac", streams)   # a silent audio track, as Instagram expects
            self.assertAlmostEqual(float(info["format"]["duration"]), 12, delta=0.6)
            self.assertLess(out.stat().st_size, 3_000_000)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        Path("content/queue").mkdir(parents=True)
        Path("posts").mkdir()

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def put(self, name, item):
        Path(f"content/queue/{name}.json").write_text(json.dumps(item))

    def test_skips_old_multi_slide_items_and_published_ones(self):
        self.put("001_old", {"id": "old", "slides": [{"heading": "h", "body": "b"}]})
        self.put("002_done", dict(ITEM, id="done"))
        self.put("003_next", dict(ITEM, id="next"))
        Path("content/state.json").write_text(json.dumps({"published": ["done"]}))
        self.assertEqual(sr.next_item()["id"], "next")

    def test_empty_queue_returns_none(self):
        self.assertIsNone(sr.next_item())

    def test_mark_published_records_item_and_ist_date(self):
        Path("posts/latest_item.txt").write_text("next")
        sr.mark_published(now=datetime(2026, 10, 28, 1, 5, tzinfo=sr.IST))
        state = json.loads(Path("content/state.json").read_text())
        self.assertEqual(state["published"], ["next"])
        self.assertEqual(state["last_posted_ist"], "2026-10-28")

    def test_mark_published_twice_does_not_duplicate(self):
        Path("posts/latest_item.txt").write_text("next")
        sr.mark_published()
        sr.mark_published()
        self.assertEqual(json.loads(Path("content/state.json").read_text())["published"], ["next"])

    def test_caption_has_hashtags_after_the_dots_and_no_source(self):
        cap = sr.build_caption(dict(ITEM, caption="Hello?", hashtags="#a #b"))
        self.assertEqual(cap, "Hello?\n\n.\n.\n.\n#a #b")


if __name__ == "__main__":
    unittest.main()
