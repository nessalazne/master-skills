#!/usr/bin/env python3
"""Tests for what the Ness edition adds. No network, no keys.

    python3 tests/test_ness.py

Jake's own suites still run as before:
    python3 skills/virality/tools/test_virality.py
    python3 skills/edit/tools/test_edit.py
    python3 skills/build/tools/test_build.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VT = ROOT / "skills" / "virality" / "tools"
ET = ROOT / "skills" / "edit" / "tools"
PUB = ROOT / "skills" / "virality-publish" / "publish.py"
SCRIPT = ROOT / "skills" / "virality" / "templates" / "script.md"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(mod)
    return mod


publish = load("publish", PUB)
results = load("results", VT / "results.py")
fit = load("fit", ET / "fit.py")


def example_script():
    text = SCRIPT.read_text()
    return text.split("-->", 1)[1]


class Swipe(unittest.TestCase):
    def run_swipe(self, rows):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps(rows))
            out = subprocess.run([sys.executable, "-I", str(VT / "swipe.py"), str(p), "--min", "1.0", "--json"],
                                 capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_supplied_median_ranks_thin_creators(self):
        rows = [{"channel": "@a", "title": None, "hook": "I saved $400 on flights", "views": 9000, "median": 500},
                {"channel": "@b", "title": None, "hook": "my routine", "views": 900, "median": 800}]
        got = self.run_swipe(rows)
        self.assertEqual(got["skipped_thin_channels"], [])
        top = got["outliers"][0]
        self.assertEqual((top["channel"], top["multiple"], top["title"]), ("@a", 18.0, "I saved $400 on flights"))

    def test_thin_without_median_still_skipped(self):
        got = self.run_swipe([{"channel": "@a", "title": "x", "views": 10}])
        self.assertEqual(got["skipped_thin_channels"], [["@a", 1]])

    def test_four_posts_use_computed_median(self):
        rows = [{"channel": "@a", "title": f"t{i}", "views": v, "median": 1} for i, v in enumerate([100, 100, 100, 400])]
        got = self.run_swipe(rows)
        self.assertEqual(got["outliers"][0]["multiple"], 4.0)


class Slop(unittest.TestCase):
    def test_ness_additions_present_and_unique(self):
        slop = json.loads((VT / "slop.json").read_text())
        finds = [e["find"].lower() for k in ("words", "phrases") for e in slop[k]]
        self.assertEqual(len(finds), len(set(finds)), "a term listed twice is counted twice by detect.py")
        for term in ("vibrant", "let's dive in", "game changer", "i hope this helps"):
            self.assertIn(term, finds)
        ids = [s["id"] for s in slop["structures"]]
        self.assertIn("announcement-opener", ids)
        self.assertNotIn("caps-shout", ids, "COVER and SCREEN lines are caps on purpose")

    def test_humanize_strips_them(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "draft.txt"
            src.write_text("Let's dive in. This vibrant tool is a game changer. I hope this helps.\n")
            out = Path(d) / "clean.txt"
            subprocess.run([sys.executable, "-I", str(VT / "humanize.py"), str(src), "-o", str(out)],
                           capture_output=True, text=True, check=True)
            clean = out.read_text().lower()
        for term in ("dive in", "vibrant", "game changer", "hope this helps"):
            self.assertNotIn(term, clean)


class PublishParse(unittest.TestCase):
    def setUp(self):
        self.s = publish.parse_script(example_script())

    def test_fields(self):
        self.assertEqual(self.s["keyword"], "PLAN")
        self.assertEqual(self.s["title"], "How I feed a family of four for $62 a week")
        self.assertTrue(self.s["text"].startswith("Comment PLAN"))
        self.assertTrue(self.s["text"].endswith("#familydinner"))
        self.assertTrue(self.s["linkedin"].startswith("We spent $250"))
        self.assertEqual(self.s["placeholders"], [])

    def test_linkedin_uses_its_own_post(self):
        t = publish.platform_texts(self.s, ["instagram", "linkedin"], {})
        self.assertNotEqual(t["instagram"], t["linkedin"])

    def test_refuses_not_truncates(self):
        s = dict(self.s, text="x" * 301)
        probs = publish.validate(s, publish.platform_texts(s, ["bluesky"], {}), ["bluesky"])
        self.assertTrue(any("bluesky" in p and "300" in p for p in probs))

    def test_placeholders_block(self):
        s = publish.parse_script(example_script().replace("$62 a week.", "{{your number}} a week."))
        probs = publish.validate(s, publish.platform_texts(s, ["instagram"], {}), ["instagram"])
        self.assertTrue(any("placeholders" in p for p in probs))

    def test_instagram_hashtag_cap(self):
        s = dict(self.s, text="hi #a #b #c #d #e #f")
        probs = publish.validate(s, {"instagram": s["text"]}, ["instagram"])
        self.assertTrue(any("hashtags" in p for p in probs))


class PublishPayloads(unittest.TestCase):
    def test_platform_fields(self):
        yt = publish.build_payload("youtube", "1", "t", "u", "now", "Title", "private")
        self.assertEqual((yt["title"], yt["privacyStatus"], yt["shouldNotifySubscribers"]), ("Title", "private", False))
        tt = publish.build_payload("tiktok", "1", "t", "u", "now")
        for k in ("privacyLevel", "disabledComments", "disabledDuet", "disabledStitch",
                  "isBrandedContent", "isYourBrand", "isAiGenerated"):
            self.assertIn(k, tt)
        self.assertEqual(publish.build_payload("instagram", "1", "t", "u", "now")["mediaType"], "reel")
        fb = publish.build_payload("facebook", "1", "t", "u", "next_slot", page_id="99")
        self.assertEqual((fb["pageId"], fb["useNextFreeSlot"]), ("99", True))

    def test_dm_body(self):
        b = publish.build_dm_body("facebook", "1", "Plan", "https://x.co", "m", "Get it here", "n", "99")
        self.assertEqual(b["triggers"][0]["keywords"], ["Plan", "PLAN", "plan"])
        self.assertIsNone(b["triggers"][0]["postId"])
        self.assertEqual(b["target"], {"targetType": "facebook", "pageId": "99"})
        self.assertTrue(b["buttons"])

    def test_find_existing(self):
        live = [{"id": 1, "accountId": "7", "isActive": True,
                 "triggers": [{"keywords": ["PLAN"], "postId": None}]},
                {"id": 2, "accountId": "7", "isActive": True,
                 "triggers": [{"keywords": ["RANK"], "postId": "55"}]},
                {"id": 3, "accountId": "7", "trigger": {"keywords": ["old"], "postId": None}}]
        self.assertEqual(publish.find_existing(live, "7", "plan")["id"], 1)
        self.assertIsNone(publish.find_existing(live, "7", "rank"), "post-scoped flows belong to one video")
        self.assertEqual(publish.find_existing(live, "7", "OLD")["id"], 3, "legacy single trigger")
        self.assertIsNone(publish.find_existing(live, "8", "plan"))

    def test_dry_run_cli(self):
        with tempfile.TemporaryDirectory() as d:
            sp = Path(d) / "virality" / "demo" / "script.md"
            sp.parent.mkdir(parents=True)
            sp.write_text(example_script())
            env = Path(d) / "empty.env"
            env.write_text("")
            clean = {k: v for k, v in os.environ.items() if not k.startswith("BLOTATO")}
            r = subprocess.run([sys.executable, "-I", str(PUB), str(sp), "--video", "https://x.co/v.mp4",
                                "--dm-url", "https://x.co/g", "--env", str(env), "--dry-run"],
                               capture_output=True, text=True, env=clean)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("<BLOTATO_ACCOUNT_INSTAGRAM>", r.stdout)
        self.assertIn("comment-received", r.stdout)


class Results(unittest.TestCase):
    def test_parse_log(self):
        log = "\n".join([
            "- 2026-10-01 12:00 | virality-publish | s | youtube | Learn | published | now | https://www.youtube.com/shorts/abcdefghijk | keyword=PLAN | hook | with pipe",
            "- 2026-10-01 12:00 | virality-publish | s | youtube | Learn | published | now | https://www.youtube.com/shorts/abcdefghijk | keyword=PLAN | hook | with pipe",
            "- 2026-10-01 12:00 | virality-publish | s | youtube | Learn | scheduled | 2026-10-09T00:00:00Z | - | keyword=PLAN | later",
            "2026-10-01 shoot it | The Payoff | hook | PLAN",
        ])
        posts = results.parse_log(log)
        self.assertEqual(len(posts), 1)
        self.assertEqual((posts[0]["hook"], posts[0]["keyword"]), ("hook | with pipe", "PLAN"))
        self.assertEqual(results.YT_ID.search(posts[0]["url"]).group(1), "abcdefghijk")
        self.assertEqual(results.IG_CODE.search("https://www.instagram.com/reel/C0de_x-1/").group(1), "C0de_x-1")


class Fit(unittest.TestCase):
    def test_math(self):
        self.assertEqual(fit.speed_needed(50, 58), 1.0)
        s = fit.speed_needed(62, 58)
        self.assertLessEqual(62 / s, 58 - fit.SAFETY + 1e-9)
        w = fit.rescale_words([{"text": "a", "start": 2.0, "end": 4.0}], 2.0)
        self.assertEqual((w[0]["start"], w[0]["end"]), (1.0, 2.0))

    def test_candidates_skip_hook_and_cta(self):
        words = []
        t = 0.0
        for n, phrase in enumerate(["hook line here.", "a very long middle phrase that runs on and on.",
                                    "short one.", "comment plan now."]):
            for wd in phrase.split():
                words.append({"text": wd, "start": t, "end": t + (0.6 if n == 1 else 0.2)})
                t += 0.7 if n == 1 else 0.25
            t += 1.0
        lines = [line for _, line in fit.cut_candidates(words)]
        self.assertTrue(lines[0].endswith("a very long middle phrase that runs on and on."))
        self.assertFalse(any("hook" in x or "comment" in x for x in lines))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg")
    def test_render(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "t.mp4", Path(d) / "t.fit.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x568:rate=30",
                            "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000", "-t", "6",
                            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)],
                           check=True)
            words = Path(d) / "t.words.json"
            words.write_text(json.dumps({"words": [{"text": "hi", "start": 1.0, "end": 1.5},
                                                   {"text": "there.", "start": 5.0, "end": 5.6}]}))
            r = subprocess.run([sys.executable, "-I", str(ET / "fit.py"), str(src), "--words", str(words),
                                "--target", "5.7", "-o", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                        "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout)
            self.assertLessEqual(dur, 5.7 + 0.05)
            scaled = json.loads((Path(d) / "t.fit.words.json").read_text())["words"]
            self.assertLess(scaled[-1]["end"], 5.7)
            r2 = subprocess.run([sys.executable, "-I", str(ET / "fit.py"), str(src), "--target", "4",
                                 "-o", str(Path(d) / "no.mp4")], capture_output=True, text=True)
            self.assertEqual(r2.returncode, 1)
            self.assertFalse((Path(d) / "no.mp4").exists(), "never hard-trims")


if __name__ == "__main__":
    unittest.main(verbosity=1)
