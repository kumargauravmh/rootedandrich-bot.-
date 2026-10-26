"""
Offline tests for post_carousel.py and the carousel builder. Instagram and GitHub are
replaced by fakes, so these check OUR logic: call order, payloads, limits, JPEG output.

    python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import carousel_reel as cr   # noqa: E402
import post_carousel as pc   # noqa: E402


class FakeResp:
    def __init__(self, ok=True, payload=None, text=""):
        self.ok, self._p, self.text = ok, payload or {}, text
        self.status_code = 200 if ok else 400

    def json(self):
        return self._p

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("HTTP error")


def slides(n):
    return [{"heading": f"Heading {i}", "body": "Body text here.\n\nSecond line."} for i in range(1, n + 1)]


class BuildTests(unittest.TestCase):
    def test_builds_one_jpeg_per_slide_at_4_5(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            paths = cr.build_carousel(slides(10), Path(d) / "c")
            self.assertEqual(len(paths), 10)
            self.assertEqual([p.name for p in paths][:2], ["slide_01.jpg", "slide_02.jpg"])
            for p in paths:
                im = Image.open(p)
                self.assertEqual((im.format, im.size, im.mode), ("JPEG", (1080, 1350), "RGB"))

    def test_post_format_defaults_to_carousel_and_rejects_nonsense(self):
        old = os.environ.pop("POST_FORMAT", None)
        try:
            self.assertEqual(cr.post_format(), "carousel")
            os.environ["POST_FORMAT"] = "REEL"
            self.assertEqual(cr.post_format(), "reel")
            os.environ["POST_FORMAT"] = "gif"
            with self.assertRaises(ValueError):
                cr.post_format()
        finally:
            os.environ.pop("POST_FORMAT", None)
            if old is not None:
                os.environ["POST_FORMAT"] = old


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._orig = (pc.requests.post, pc.push_slides_to_media_repo, pc.wait_until_public,
                      pc.pr.wait_until_ready, pc.pr.publish_container)
        os.environ.update(IG_USER_ID="123", IG_ACCESS_TOKEN="tok")
        self.counter = 0

        def fake_post(url, data=None):
            self.calls.append(("post", url, dict(data)))
            self.counter += 1
            return FakeResp(payload={"id": f"id{self.counter}"})

        pc.requests.post = fake_post
        pc.push_slides_to_media_repo = lambda paths, slug: [f"https://x/{p.name}" for p in paths]
        pc.wait_until_public = lambda url: None
        pc.pr.wait_until_ready = lambda cid, tok: self.calls.append(("ready", cid))
        pc.pr.publish_container = lambda uid, tok, cid: (self.calls.append(("publish", cid)) or {"id": "post1"})
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = [Path(self.tmp.name) / f"slide_{i:02d}.jpg" for i in range(1, 11)]

    def tearDown(self):
        (pc.requests.post, pc.push_slides_to_media_repo, pc.wait_until_public,
         pc.pr.wait_until_ready, pc.pr.publish_container) = self._orig
        self.tmp.cleanup()

    def test_full_flow_order_and_payloads(self):
        pc.publish_carousel(self.paths, "my caption", "slug")
        posts = [c for c in self.calls if c[0] == "post"]
        self.assertEqual(len(posts), 11)  # 10 children + 1 parent
        for _, url, data in posts[:10]:
            self.assertTrue(url.endswith("/123/media"))
            self.assertEqual(data["is_carousel_item"], "true")
            self.assertTrue(data["image_url"].startswith("https://x/slide_"))
            self.assertNotIn("caption", data)  # captions belong on the parent only
        _, _, parent = posts[10]
        self.assertEqual(parent["media_type"], "CAROUSEL")
        self.assertEqual(parent["caption"], "my caption")
        self.assertEqual(parent["children"], ",".join(f"id{i}" for i in range(1, 11)))
        self.assertEqual(self.calls[-1], ("publish", "id11"))

    def test_children_keep_slide_order(self):
        pc.publish_carousel(self.paths, "c", "slug")
        posts = [c for c in self.calls if c[0] == "post"][:10]  # children only, not the parent
        urls = [c[2]["image_url"] for c in posts]
        self.assertEqual(urls, [f"https://x/slide_{i:02d}.jpg" for i in range(1, 11)])

    def test_each_child_waits_until_ready_before_the_next(self):
        pc.publish_carousel(self.paths, "c", "slug")
        kinds = [c[0] for c in self.calls]
        self.assertEqual(kinds[:4], ["post", "ready", "post", "ready"])

    def test_rejects_too_many_slides(self):
        with self.assertRaises(ValueError):
            pc.publish_carousel(self.paths + [Path("slide_11.jpg")], "c", "slug")
        self.assertEqual(self.calls, [])  # nothing sent

    def test_rejects_single_slide(self):
        with self.assertRaises(ValueError):
            pc.publish_carousel(self.paths[:1], "c", "slug")

    def test_rejects_png(self):
        with self.assertRaises(ValueError):
            pc.publish_carousel([Path("a.png"), Path("b.png")], "c", "slug")

    def test_rejects_overlong_caption(self):
        with self.assertRaises(ValueError):
            pc.publish_carousel(self.paths, "x" * 2201, "slug")
        self.assertEqual(self.calls, [])

    def test_meta_error_stops_the_run_and_never_publishes(self):
        def failing_post(url, data=None):
            return FakeResp(ok=False, text='{"error":{"message":"Error validating access token","code":190}}')
        pc.requests.post = failing_post
        with self.assertRaises(RuntimeError):
            pc.publish_carousel(self.paths, "c", "slug")
        self.assertNotIn("publish", [c[0] for c in self.calls])


class DispatchTests(unittest.TestCase):
    def test_reel_format_hands_over_to_post_reel(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                Path("posts").mkdir()
                Path("posts/latest_format.txt").write_text("reel")
                called = []
                orig = pc.pr.main
                pc.pr.main = lambda: called.append(True)
                try:
                    pc.main()
                finally:
                    pc.pr.main = orig
                self.assertEqual(called, [True])
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
