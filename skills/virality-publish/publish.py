#!/usr/bin/env python3
"""
publish.py - post a finished /virality video through Blotato, and wire the comment keyword.

Ness edition. Ported from nessalazne/instagram-agent-skill ig-publish/publish.py (MIT) and
generalised to every short-form platform Blotato posts to. The DM automation body follows the
one youtube-repurposer runs in production.

The script never decides to post. The skill that calls it has already collected an explicit
"publish" for this exact script and video.

    python3 publish.py virality/<slug>/script.md --video final.mp4 --dry-run
    python3 publish.py virality/<slug>/script.md --video final.mp4
    python3 publish.py virality/<slug>/script.md --video final.mp4 --platforms instagram,tiktok,youtube,linkedin
    python3 publish.py virality/<slug>/script.md --video final.mp4 --schedule 2026-10-12T16:00:00Z
    python3 publish.py virality/<slug>/script.md --video final.mp4 --dm-url https://example.com/guide
    python3 publish.py virality/<slug>/script.md --dm-url https://example.com/guide --dm-only
    python3 publish.py virality/<slug>/script.md --dm-url https://example.com/guide --dm-only --dm-replace
    python3 publish.py --check --platforms instagram,tiktok,youtube,facebook

What it reads from script.md (the /virality output format):
    - keyword: PLAN            the comment keyword, used by the DM automation
    ## Caption + ## Hashtags   the post text on every platform
    TITLE: ... under ## Cover  the YouTube title
    ## LinkedIn post           used as the LinkedIn text when present
Override any platform's text with --text PLATFORM=path/to/file.txt.

It refuses rather than truncates. If one platform's text is over its limit, nothing is
uploaded and nothing is posted: fix the text, pass --text, or drop that platform.

Keys come from ~/.claude/virality/.env (or --env PATH), falling back to the process environment:

    BLOTATO_API_KEY=...
    BLOTATO_ACCOUNT_INSTAGRAM=1234
    BLOTATO_ACCOUNT_TIKTOK=1234
    BLOTATO_ACCOUNT_YOUTUBE=1234
    BLOTATO_ACCOUNT_FACEBOOK=1234      + BLOTATO_FACEBOOK_PAGE_ID=...
    BLOTATO_ACCOUNT_LINKEDIN=1234      (and _TWITTER, _THREADS, _BLUESKY)

Python 3 standard library only.

Exit codes: 0 done (every post reached a terminal state), 1 a post or the DM step failed,
2 bad input (nothing was sent).
"""

import argparse
import datetime as dt
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MCP_URL = "https://mcp.blotato.com/mcp"
REST_URL = "https://backend.blotato.com/v2"
DEFAULT_ENV = Path.home() / ".claude" / "virality" / ".env"
LOG_PATH = Path.home() / ".claude" / "virality" / "log.md"
TERMINAL = ("published", "scheduled", "failed", "completed")
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
HASHTAG_RE = re.compile(r"(?:^|\s)(#[A-Za-z0-9_]+)")

PLATFORMS = ["instagram", "tiktok", "youtube", "facebook", "linkedin", "twitter", "threads", "bluesky"]
DEFAULT_PLATFORMS = ["instagram", "tiktok", "youtube"]
# Characters each platform takes in the post text. Over the limit = refused, never cut.
TEXT_LIMIT = {"instagram": 2200, "tiktok": 2200, "youtube": 5000, "facebook": 5000,
              "linkedin": 3000, "twitter": 280, "threads": 500, "bluesky": 300}
YT_TITLE_LIMIT = 100
IG_HASHTAG_LIMIT = 5
# Blotato comment-triggered DMs exist on Instagram and Facebook pages only. TikTok has none.
DM_PLATFORMS = ("instagram", "facebook")
BUTTON_TITLE_LIMIT = 20    # Blotato rejects longer button titles with a 400


# ── env ───────────────────────────────────────────────────────────────────────

def load_env(path: Path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def env(key: str) -> str:
    return os.environ.get(key, "").strip()


def require(key: str) -> str:
    val = env(key)
    if not val:
        sys.exit(f"{key} is not set. Put it in {DEFAULT_ENV} or pass --env.")
    return val


def account_key(platform: str) -> str:
    return f"BLOTATO_ACCOUNT_{platform.upper()}"


# ── script.md ─────────────────────────────────────────────────────────────────

def sections(md: str) -> dict:
    """{'caption': '...', 'hashtags': '...', ...} keyed by lower-case ## heading."""
    out, current, buf = {}, None, []
    for line in md.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m and not line.startswith("###"):
            if current is not None:
                out[current] = "\n".join(buf).strip()
            current, buf = m.group(1).strip().lower(), []
        elif current is not None:
            buf.append(line)
    if current is not None:
        out[current] = "\n".join(buf).strip()
    return out


def parse_script(md: str) -> dict:
    sec = sections(md)
    kw = re.search(r"^-\s*keyword:\s*([A-Za-z0-9_-]+)\s*$", md, re.M | re.I)
    cover = sec.get("cover", "")
    title = re.search(r"^TITLE:\s*(.+?)\s*$", cover, re.M)
    linkedin = next((v for k, v in sec.items() if k.startswith("linkedin post")), "")
    caption = sec.get("caption", "")
    hashtags = sec.get("hashtags", "")
    text = caption + (("\n\n" + hashtags) if hashtags else "")
    return {
        "keyword": kw.group(1) if kw else "",
        "title": title.group(1) if title else "",
        "caption": caption,
        "text": text.strip(),
        "linkedin": linkedin.strip(),
        "hook": caption.strip().splitlines()[0][:140] if caption.strip() else "",
        "placeholders": re.findall(r"\{\{[^}]+\}\}", md),
    }


def platform_texts(script: dict, platforms: list, overrides: dict) -> dict:
    texts = {}
    for p in platforms:
        if p in overrides:
            texts[p] = overrides[p]
        elif p == "linkedin" and script["linkedin"]:
            texts[p] = script["linkedin"]
        else:
            texts[p] = script["text"]
    return texts


def validate(script: dict, texts: dict, platforms: list) -> list:
    """Every problem at once, so one rerun fixes them all."""
    problems = []
    if script["placeholders"]:
        problems.append(f"the script still has placeholders: {', '.join(sorted(set(script['placeholders'])))}")
    for p in platforms:
        t = texts.get(p, "")
        if not t.strip():
            problems.append(f"{p}: the text is empty (no ## Caption in the script and no --text {p}=...)")
            continue
        if len(t) > TEXT_LIMIT[p]:
            problems.append(f"{p}: text is {len(t):,} characters, the limit is {TEXT_LIMIT[p]:,} "
                            f"(pass --text {p}=short.txt or drop {p})")
        if p == "instagram":
            tags = HASHTAG_RE.findall(t)
            if len(tags) > IG_HASHTAG_LIMIT:
                problems.append(f"instagram: {len(tags)} hashtags, the cap is {IG_HASHTAG_LIMIT}")
    if "youtube" in platforms:
        if not script["title"]:
            problems.append("youtube: no TITLE: line under ## Cover")
        elif len(script["title"]) > YT_TITLE_LIMIT:
            problems.append(f"youtube: title is {len(script['title'])} characters, the limit is {YT_TITLE_LIMIT}")
    return problems


# ── payloads ──────────────────────────────────────────────────────────────────

def check_schedule(schedule: str):
    if schedule in ("now", "next_slot"):
        return
    try:
        when = dt.datetime.fromisoformat(schedule.replace("Z", "+00:00"))
    except ValueError:
        sys.exit(f"--schedule must be now, next_slot, or an ISO 8601 UTC time, got {schedule!r}")
    if when.tzinfo is None:
        sys.exit(f"--schedule needs a timezone, e.g. {schedule}Z for UTC")
    if when < dt.datetime.now(dt.timezone.utc):
        sys.exit(f"--schedule {schedule} is in the past.")


def build_payload(platform: str, account_id: str, text: str, media_url: str, schedule: str,
                  title: str = "", privacy: str = "private", page_id: str = "") -> dict:
    args = {"accountId": str(account_id), "platform": platform, "text": text, "mediaUrls": [media_url]}
    if platform == "instagram":
        args["mediaType"] = "reel"
    elif platform == "facebook":
        args["mediaType"] = "reel"
        args["pageId"] = page_id
    elif platform == "youtube":
        args["title"] = title
        args["privacyStatus"] = privacy
        args["shouldNotifySubscribers"] = privacy == "public"
    elif platform == "tiktok":
        args.update({"privacyLevel": "PUBLIC_TO_EVERYONE", "disabledComments": False,
                     "disabledDuet": False, "disabledStitch": False, "isBrandedContent": False,
                     "isYourBrand": False, "isAiGenerated": False})
    if schedule == "next_slot":
        args["useNextFreeSlot"] = True
    elif schedule and schedule != "now":
        args["scheduledTime"] = schedule
    return args


def keyword_variants(keyword: str) -> list:
    # Blotato does not document whether keyword matching is case-sensitive, so send all three.
    return list(dict.fromkeys([keyword, keyword.upper(), keyword.lower()]))


DM_TEMPLATE = "Thanks for commenting {kw}! Tap the button below to get it."


def build_dm_body(platform: str, account_id: str, keyword: str, url: str, message: str,
                  button: str, name: str, page_id: str = "") -> dict:
    target = {"targetType": platform}
    if page_id:
        target["pageId"] = page_id
    return {
        "accountId": str(account_id),
        "platform": platform,
        "name": name[:60],
        "dmMessage": message,
        "buttons": [{"type": "url", "title": button, "url": url}],
        "isActive": True,
        "target": target,
        "triggers": [{"type": "comment-received", "keywords": keyword_variants(keyword),
                      "postId": None, "isActive": True}],
    }


def triggers_of(flow: dict) -> list:
    # Blotato moved from one `trigger` object to a `triggers` array in September 2026.
    if isinstance(flow.get("triggers"), list):
        return flow["triggers"]
    return [flow["trigger"]] if flow.get("trigger") else []


def find_existing(automations: list, account_id: str, keyword: str):
    """A live automation on this account that already answers the keyword on any post."""
    kw = keyword.lower()
    for a in automations or []:
        if str(a.get("accountId")) != str(account_id) or a.get("isActive") is False:
            continue
        for t in triggers_of(a):
            if t.get("postId") is None and any(str(k).lower() == kw for k in t.get("keywords") or []):
                return a
    return None


# ── Blotato ───────────────────────────────────────────────────────────────────

def _http(method: str, url: str, body=None, headers=None, data: bytes = None, timeout: int = 60):
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach {urllib.parse.urlsplit(url).netloc}: {e.reason}")


def rest(method: str, path: str, body=None):
    status, text = _http(method, f"{REST_URL}{path}", body,
                         {"blotato-api-key": require("BLOTATO_API_KEY"), "Accept": "application/json"})
    if status >= 400:
        raise RuntimeError(f"Blotato {method} {path} HTTP {status}: {text[:300]}")
    return json.loads(text) if text.strip() else {}


_rpc_id = 0


def _parse_rpc_body(text: str) -> dict:
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                return json.loads(payload)
    raise RuntimeError(f"Unparseable MCP response: {text[:200]}")


def rpc(tool: str, arguments: dict, timeout: int = 60):
    global _rpc_id
    _rpc_id += 1
    status, text = _http("POST", MCP_URL,
                         {"jsonrpc": "2.0", "method": "tools/call",
                          "params": {"name": tool, "arguments": arguments}, "id": _rpc_id},
                         {"blotato-api-key": require("BLOTATO_API_KEY"),
                          "Accept": "application/json, text/event-stream"}, timeout=timeout)
    if status >= 400:
        raise RuntimeError(f"Blotato MCP {tool} HTTP {status}: {text[:300]}")
    data = _parse_rpc_body(text)
    if data.get("error"):
        raise RuntimeError(f"Blotato MCP {tool} error: {data['error']}")
    result = data.get("result", {})
    if result.get("isError"):
        raise RuntimeError(f"Blotato MCP {tool} tool error: {result}")
    content = result.get("content") or []
    if content and content[0].get("type") == "text":
        try:
            return json.loads(content[0]["text"])
        except json.JSONDecodeError:
            return content[0]["text"]
    return result


def upload_media(path: Path) -> str:
    print(f"Uploading {path.name} ({path.stat().st_size / 1048576:.1f} MB) to Blotato...")
    res = rpc("blotato_create_presigned_upload_url", {"filename": path.name})
    presigned = res.get("presignedUrl") or res.get("uploadUrl")
    public = res.get("publicUrl") or res.get("url")
    if not presigned or not public:
        sys.exit(f"Blotato presigned URL response missing expected fields: {res}")
    # Without a Content-Type the file is served as application/octet-stream, which
    # Instagram's media fetch can refuse.
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    status, text = _http("PUT", presigned, data=path.read_bytes(), headers={"Content-Type": ctype}, timeout=1800)
    if status >= 400:
        sys.exit(f"Upload PUT failed {status}: {text[:200]}")
    print("Upload complete.")
    return public


def poll(submission_id: str, max_wait: int) -> dict:
    """Video posts transcode on the platform's side, so this can take a few minutes."""
    deadline = time.time() + max_wait
    last = {}
    while time.time() < deadline:
        time.sleep(20)
        try:
            data = rpc("blotato_get_post_status", {"postSubmissionId": str(submission_id)})
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        last = data
        status = str(data.get("status", "")).lower()
        if status in TERMINAL:
            return data
        print(f"  {submission_id}: {status or 'in-progress'} ...", flush=True)
    last.setdefault("status", "timeout")
    return last


def list_accounts() -> list:
    res = rpc("blotato_list_accounts", {}, timeout=30)
    if isinstance(res, dict):
        for key in ("accounts", "items", "data"):
            if isinstance(res.get(key), list):
                return res[key]
    return res if isinstance(res, list) else []


def name_accounts(pins: dict) -> dict:
    """{platform: 'name'} for every pinned id, or exit. An id alone names nothing: one Blotato
    workspace can hold several accounts on the same platform."""
    accounts = {str(a.get("id")): a for a in list_accounts()}
    names, problems = {}, []
    for platform, account_id in pins.items():
        acc = accounts.get(str(account_id))
        if not acc:
            problems.append(f"{platform}: account {account_id} is not in this Blotato workspace")
            continue
        actual = str(acc.get("platform", "")).lower()
        label = acc.get("username") or acc.get("fullname") or acc.get("name") or "?"
        if actual != platform:
            problems.append(f"{platform}: account {account_id} is {actual or 'unknown'} ({label})")
            continue
        names[platform] = f"@{label}" if acc.get("username") else label
    if problems:
        sys.exit("Not sent:\n  " + "\n  ".join(problems))
    return names


def list_automations() -> list:
    res = rest("GET", "/dm-automations?limit=250")
    if isinstance(res, list):
        return res
    return res.get("items") or res.get("flows") or res.get("automations") or []


# ── log ───────────────────────────────────────────────────────────────────────

def append_log(slug: str, platform: str, account: str, status: str, schedule: str, url: str,
               keyword: str, hook: str):
    """One line per post. results.py reads the url back to fetch views for step 2."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        with LOG_PATH.open("a") as fh:
            fh.write(f"- {stamp} | virality-publish | {slug} | {platform} | {account} | {status} | "
                     f"{schedule} | {url or '-'} | keyword={keyword or '-'} | {hook}\n")
    except OSError as exc:
        print(f"(could not write {LOG_PATH}: {exc})", file=sys.stderr)


# ── main ──────────────────────────────────────────────────────────────────────

def parse_platforms(raw: str) -> list:
    chosen = [p.strip().lower() for p in raw.split(",") if p.strip()]
    bad = [p for p in chosen if p not in PLATFORMS]
    if bad:
        sys.exit(f"Unknown platform(s): {', '.join(bad)}. Choose from {', '.join(PLATFORMS)}.")
    return list(dict.fromkeys(chosen))


def parse_overrides(items: list) -> dict:
    out = {}
    for item in items or []:
        if "=" not in item:
            sys.exit(f"--text wants PLATFORM=path, got {item!r}")
        p, path = item.split("=", 1)
        p = p.strip().lower()
        if p not in PLATFORMS:
            sys.exit(f"--text: unknown platform {p!r}")
        out[p] = Path(path).expanduser().read_text().strip()
    return out


def main():
    ap = argparse.ArgumentParser(description="Post a finished /virality video through Blotato.")
    ap.add_argument("script", nargs="?", help="virality/<slug>/script.md")
    ap.add_argument("--video", help="the rendered video: a file or a hosted URL")
    ap.add_argument("--platforms", default=",".join(DEFAULT_PLATFORMS),
                    help=f"comma list (default {','.join(DEFAULT_PLATFORMS)}); any of {','.join(PLATFORMS)}")
    ap.add_argument("--text", action="append", metavar="PLATFORM=FILE", help="override one platform's text")
    ap.add_argument("--schedule", default="now", help="now (default), next_slot, or ISO 8601 UTC time")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"],
                    help="YouTube privacy (default private: a wrong-channel private upload is invisible)")
    ap.add_argument("--account", action="append", metavar="PLATFORM=ID", help="override one platform's account id")
    ap.add_argument("--dm-url", help="turn on the comment-keyword DM: the link the button opens")
    ap.add_argument("--dm-message", help="DM text (default: a short 'tap the button below' line)")
    ap.add_argument("--dm-button", default="Get it here", help=f"button title, {BUTTON_TITLE_LIMIT} characters max")
    ap.add_argument("--dm-only", action="store_true", help="only set up the DM automation, post nothing")
    ap.add_argument("--dm-replace", action="store_true",
                    help="rewrite an existing automation for the same keyword (default: leave it alone)")
    ap.add_argument("--env", type=Path, default=DEFAULT_ENV, help=f"env file (default {DEFAULT_ENV})")
    ap.add_argument("--dry-run", action="store_true", help="print every payload and exit, no network")
    ap.add_argument("--check", action="store_true", help="name each pinned account and exit")
    ap.add_argument("--max-wait", type=int, default=600, help="seconds to poll each post (default 600)")
    a = ap.parse_args()

    load_env(a.env)
    platforms = parse_platforms(a.platforms)
    pins = {p: env(account_key(p)) for p in platforms}
    for item in a.account or []:
        if "=" not in item:
            sys.exit(f"--account wants PLATFORM=ID, got {item!r}")
        p, i = item.split("=", 1)
        pins[p.strip().lower()] = i.strip()
    page_id = env("BLOTATO_FACEBOOK_PAGE_ID")

    if a.check:
        missing = [account_key(p) for p, i in pins.items() if not i]
        if missing:
            sys.exit(f"Not set: {', '.join(missing)}")
        for p, label in name_accounts(pins).items():
            print(f"OK  {p:<10} {pins[p]:>8}  {label}")
        return

    if not a.script:
        ap.error("the script.md path is required unless --check is given")
    script_path = Path(a.script).expanduser()
    script = parse_script(script_path.read_text())
    slug = script_path.parent.name or script_path.stem
    texts = platform_texts(script, platforms, parse_overrides(a.text))

    problems = [] if a.dm_only else validate(script, texts, platforms)
    if not a.dm_only:
        if not a.video:
            problems.append("--video is required (or pass --dm-only)")
        elif not a.video.startswith(("http://", "https://")):
            vp = Path(a.video).expanduser()
            if not vp.exists():
                problems.append(f"video not found: {a.video}")
            elif vp.suffix.lower() not in VIDEO_EXT:
                problems.append(f"--video wants {', '.join(sorted(VIDEO_EXT))}, got {vp.name}")
        if "facebook" in platforms and not page_id:
            problems.append("facebook: BLOTATO_FACEBOOK_PAGE_ID is not set")
    dm_platforms = [p for p in platforms if p in DM_PLATFORMS]
    if a.dm_url:
        if not script["keyword"]:
            problems.append("--dm-url: no '- keyword: WORD' line in the script")
        if not a.dm_url.startswith(("http://", "https://")):
            problems.append("--dm-url must be a full http(s) link")
        if len(a.dm_button) > BUTTON_TITLE_LIMIT:
            problems.append(f"--dm-button is {len(a.dm_button)} characters, Blotato allows {BUTTON_TITLE_LIMIT}")
        if not dm_platforms:
            problems.append("--dm-url: DMs work on instagram and facebook only; add one to --platforms")
    elif a.dm_only:
        problems.append("--dm-only needs --dm-url")
    if not a.dry_run:
        missing = [account_key(p) for p in platforms if not pins.get(p)]
        if missing:
            problems.append(f"not set: {', '.join(missing)}")
    if problems:
        print("Not sent. Fix these and rerun:\n  " + "\n  ".join(problems), file=sys.stderr)
        sys.exit(2)
    check_schedule(a.schedule)

    dm_message = a.dm_message or DM_TEMPLATE.format(kw=script["keyword"])
    dm_name = f"{script['keyword']} - {slug}"

    if a.dry_run:
        media = a.video if a.video and a.video.startswith("http") else f"<upload of {a.video}>"
        if not a.dm_only:
            for p in platforms:
                print(f"# {p}")
                print(json.dumps(build_payload(p, pins.get(p) or f"<{account_key(p)}>", texts[p], media,
                                               a.schedule, script["title"], a.privacy, page_id),
                                 indent=2, ensure_ascii=False))
        if a.dm_url:
            for p in dm_platforms:
                print(f"# DM automation, {p} (created; an existing '{script['keyword']}' one is kept "
                      f"unless --dm-replace)")
                print(json.dumps(build_dm_body(p, pins.get(p) or f"<{account_key(p)}>", script["keyword"],
                                               a.dm_url, dm_message, a.dm_button, dm_name,
                                               page_id if p == "facebook" else ""),
                                 indent=2, ensure_ascii=False))
        return

    names = name_accounts(pins)
    failed = False

    if not a.dm_only:
        media_url = a.video if a.video.startswith(("http://", "https://")) else upload_media(Path(a.video).expanduser())
        submitted = []
        for p in platforms:
            payload = build_payload(p, pins[p], texts[p], media_url, a.schedule, script["title"], a.privacy, page_id)
            print(f"Submitting to {p} {names[p]} (schedule={a.schedule})...")
            try:
                res = rpc("blotato_create_post", payload, timeout=90)
            except Exception as exc:
                print(f"  FAILED {exc}")
                append_log(slug, p, names[p], "failed", a.schedule, "", script["keyword"], script["hook"])
                failed = True
                continue
            sub_id = None
            if isinstance(res, dict):
                sub_id = res.get("postSubmissionId") or res.get("submissionId") or res.get("id")
            submitted.append((p, sub_id, res))
            time.sleep(2)
        for p, sub_id, res in submitted:
            final = res if isinstance(res, dict) and str(res.get("status", "")).lower() in TERMINAL else (
                poll(sub_id, a.max_wait) if sub_id else {"status": "submitted"})
            status = str(final.get("status", "")).lower()
            url = final.get("publicUrl") or final.get("url") or ""
            append_log(slug, p, names[p], status, a.schedule, url, script["keyword"], script["hook"])
            if status in ("published", "completed"):
                print(f"PUBLISHED  {p:<10} {url or '(no public URL yet, check Blotato)'}")
            elif status == "scheduled":
                print(f"SCHEDULED  {p:<10} {final.get('scheduledTime') or a.schedule}")
            elif status == "submitted":
                print(f"SUBMITTED  {p:<10} Blotato returned no submission id to track: check Blotato before retrying")
                failed = True
            elif status == "timeout":
                print(f"PENDING    {p:<10} still processing after {a.max_wait}s, submission {sub_id}")
                failed = True
            else:
                err = final.get("errorMessage") or final.get("error") or json.dumps(final)[:200]
                print(f"FAILED     {p:<10} {status}: {err}")
                failed = True

    if a.dm_url:
        try:
            existing = list_automations()
        except Exception as exc:
            print(f"(could not list automations to dedupe, so none were touched: {exc})")
            sys.exit(1)
        for p in dm_platforms:
            body = build_dm_body(p, pins[p], script["keyword"], a.dm_url, dm_message, a.dm_button,
                                 dm_name, page_id if p == "facebook" else "")
            found = find_existing(existing, pins[p], script["keyword"])
            try:
                if found and not a.dm_replace:
                    # Another tool (or an older video) already owns this keyword on this account.
                    # Rewriting it would change what that video's commenters get, so ask first.
                    btn = ((found.get("buttons") or [{}])[0] or {}).get("url", "?")
                    print(f"DM KEPT    {p:<10} '{script['keyword']}' already has automation {found['id']} "
                          f"(sends {btn}). Left as is; rerun with --dm-replace to point it at {a.dm_url}")
                elif found:
                    # PATCH on an active automation goes live at once. The body must be wrapped.
                    rest("PATCH", f"/dm-automations/{found['id']}",
                         {"patch": {"dmMessage": body["dmMessage"], "buttons": body["buttons"]}})
                    print(f"DM UPDATED {p:<10} '{script['keyword']}' automation {found['id']} now sends {a.dm_url}")
                else:
                    res = rest("POST", "/dm-automations", body)
                    new_id = (res.get("flow") or {}).get("id") or res.get("id")
                    print(f"DM LIVE    {p:<10} '{script['keyword']}' automation {new_id} on any post")
            except Exception as exc:
                print(f"DM FAILED  {p:<10} {exc}")
                failed = True
            time.sleep(2)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
