#!/usr/bin/env python3
"""results.py - read back how your own /virality posts did, so step 2 starts from your numbers.

Ness edition. New in this fork.

/virality-publish writes one line per post to ~/.claude/virality/log.md, with the public URL.
This reads those lines, fetches the current view counts, prints them, and writes
~/.claude/virality/results.json in the shape collect.py reads:

    python3 results.py                  # fetch and print, write results.json
    python3 results.py --dry-run        # list what would be fetched and what it costs
    python3 results.py --no-instagram   # YouTube only (free), skip the Apify call
    python3 collect.py ~/.claude/virality/results.json -o virality/<slug>/candidates.json

Where the numbers come from:
    YouTube    the Data API `videos` call, 1 quota unit per 50 videos (YOUTUBE_API_KEY, free)
    Instagram  Apify's profile scraper for each account in the log, one run, about $0.0026 per
               account, matched on the post's shortcode. Only the account's latest 12 posts come
               back, so an older reel shows as "not in the latest 12".
    Others     TikTok, Facebook, LinkedIn, X, Threads and Bluesky have no read path here. They are
               listed so you can paste the numbers by hand.

Keys come from ~/.claude/virality/.env, as in fetch_youtube.py and fetch_instagram.py.
Python 3 standard library only. Exit codes: 0 fetched, 1 nothing to fetch, 2 bad input.
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fetch_instagram as ig  # noqa: E402
import fetch_youtube as yt    # noqa: E402

LOG_PATH = Path.home() / ".claude" / "virality" / "log.md"
OUT_PATH = Path.home() / ".claude" / "virality" / "results.json"

YT_ID = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/)|youtu\.be/)([\w-]{11})")
IG_CODE = re.compile(r"instagram\.com/(?:[\w.]+/)?(?:reel|reels|p|tv)/([\w-]+)")


def parse_log(text: str) -> list:
    """Posts from /virality-publish lines that have a public URL. Other lines are ignored."""
    posts = []
    for line in text.splitlines():
        if "| virality-publish |" not in line:
            continue
        parts = [p.strip() for p in line.lstrip("- ").split(" | ")]
        if len(parts) < 10:
            continue
        stamp, _, slug, platform, account, status, _schedule, url, keyword = parts[:9]
        hook = " | ".join(parts[9:])
        if not url.startswith("http"):
            continue
        posts.append({"posted": stamp[:10], "slug": slug, "platform": platform, "account": account,
                      "status": status, "url": url, "keyword": keyword.replace("keyword=", ""),
                      "hook": hook})
    # One row per URL: a re-run logs the same post twice.
    return list({p["url"]: p for p in posts}.values())


def youtube_views(posts: list, key: str) -> dict:
    ids = {}
    for p in posts:
        m = YT_ID.search(p["url"])
        if m:
            ids[m.group(1)] = p["url"]
    views = {}
    id_list = list(ids)
    for i in range(0, len(id_list), 50):
        data = yt.get("videos", {"part": "statistics", "id": ",".join(id_list[i:i + 50])}, key)
        for item in data.get("items", []):
            views[ids[item["id"]]] = int(item.get("statistics", {}).get("viewCount", 0) or 0)
    return views


def instagram_views(posts: list) -> dict:
    handles = sorted({p["account"].lstrip("@") for p in posts if p["account"].startswith("@")})
    if not handles:
        return {}
    items = ig.run_actor(ig.PROFILE_ACTOR, {"usernames": handles}, ig.estimate(0, len(handles)) * 1.2 + 0.01)
    by_code = {}
    for profile in items:
        for raw in profile.get("latestPosts") or []:
            code = raw.get("shortCode") or raw.get("shortcode")
            if code:
                by_code[code] = ig._views(raw)
    views = {}
    for p in posts:
        m = IG_CODE.search(p["url"])
        if m and m.group(1) in by_code:
            views[p["url"]] = by_code[m.group(1)]
    return views


def main():
    ap = argparse.ArgumentParser(description="Fetch view counts for your own /virality posts.")
    ap.add_argument("--log", type=Path, default=LOG_PATH, help=f"log file (default {LOG_PATH})")
    ap.add_argument("-o", "--out", type=Path, default=OUT_PATH, help=f"output (default {OUT_PATH})")
    ap.add_argument("--no-instagram", action="store_true", help="skip the paid Apify call")
    ap.add_argument("--dry-run", action="store_true", help="show what would be fetched, spend nothing")
    a = ap.parse_args()

    if not a.log.exists():
        print(f"No log at {a.log} yet. /virality-publish writes it after the first post.", file=sys.stderr)
        sys.exit(1)
    posts = parse_log(a.log.read_text())
    if not posts:
        print(f"No published posts with a URL in {a.log}.", file=sys.stderr)
        sys.exit(1)

    yt_posts = [p for p in posts if p["platform"] == "youtube"]
    ig_posts = [p for p in posts if p["platform"] == "instagram"]
    other = [p for p in posts if p["platform"] not in ("youtube", "instagram")]
    ig_handles = sorted({p["account"] for p in ig_posts})

    if a.dry_run:
        print(f"{len(posts)} posts in the log")
        print(f"  youtube    {len(yt_posts):3d}  Data API, about {max(1, -(-len(yt_posts) // 50))} unit(s), free")
        cost = ig.estimate(0, len(ig_handles))
        note = "skipped (--no-instagram)" if a.no_instagram else f"Apify, {len(ig_handles)} profile(s), est. ${cost:.4f}"
        print(f"  instagram  {len(ig_posts):3d}  {note}")
        print(f"  by hand    {len(other):3d}  {', '.join(sorted({p['platform'] for p in other})) or '-'}")
        return

    views = {}
    if yt_posts:
        key = yt.load_key()
        if key:
            views.update(youtube_views(yt_posts, key))
        else:
            print("YOUTUBE_API_KEY is not set, YouTube skipped.", file=sys.stderr)
    if ig_posts and not a.no_instagram:
        ig.load_env(ig.DEFAULT_ENV)
        ig.load_env(ig.FALLBACK_ENV)
        if ig.os.environ.get("APIFY_TOKEN"):
            ig.announce(f"1 run of {ig.PROFILE_ACTOR}, {len(ig_handles)} profile(s)", ig.estimate(0, len(ig_handles)))
            views.update(instagram_views(ig_posts))
        else:
            print("APIFY_TOKEN is not set, Instagram skipped.", file=sys.stderr)

    rows = []
    print(f"\n  {'views':>9}  {'platform':<10} {'posted':<10}  hook")
    for p in sorted(posts, key=lambda p: (p["platform"], p["posted"])):
        v = views.get(p["url"])
        if v is None:
            why = ("paste by hand" if p in other else
                   "not in the latest 12" if p["platform"] == "instagram" and not a.no_instagram else "not fetched")
            print(f"  {'-':>9}  {p['platform']:<10} {p['posted']:<10}  {p['hook'][:60]}  ({why})")
            continue
        print(f"  {v:>9,}  {p['platform']:<10} {p['posted']:<10}  {p['hook'][:60]}")
        rows.append({"channel": f"{p['account']} ({p['platform']})", "title": p["hook"], "hook": p["hook"],
                     "views": v, "url": p["url"], "posted": p["posted"],
                     "platform": "shorts" if p["platform"] == "youtube" else "reels"})
    if not rows:
        print("\n  nothing fetched")
        sys.exit(1)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    print(f"\n  wrote {a.out} ({len(rows)} posts)  ->  python3 collect.py {a.out} -o candidates.json\n")


if __name__ == "__main__":
    main()
