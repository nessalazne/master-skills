---
name: virality-publish
description: >-
  Post a finished /virality video to Instagram, TikTok, YouTube Shorts and other platforms through
  Blotato, then wire the comment keyword to an automatic DM with the user's link. Runs only after
  the user types "publish" for a specific script and rendered video. Use when the user says
  "publish this", "post it", "schedule it", "send it to my accounts", "set up the keyword DM", or
  has a virality/<slug>/script.md plus a rendered video and wants it live. Ness edition addition
  to Jake's master-skills.
---

# virality-publish

The last step after /virality and /edit: the shoot-ready script is shot, edited and rendered, and
now it goes out. `publish.py` reads the caption, hashtags, YouTube title and comment keyword from
`virality/<slug>/script.md`, uploads the video once, posts it to each platform, polls every post
until it is published, scheduled or failed, and logs the public URLs for `results.py`.

With `--dm-url`, it also sets up the CTA the script promised: anyone who comments the keyword on
Instagram or Facebook gets a DM with a button that opens the user's link.

```bash
P=skills/virality-publish/publish.py   # run from the repo, or ~/.claude/skills/virality-publish
python3 $P --check --platforms instagram,tiktok,youtube           # which accounts are pinned?
python3 $P virality/<slug>/script.md --video edit/final.master.mp4 --dry-run
python3 $P virality/<slug>/script.md --video edit/final.master.mp4 --dm-url https://...
python3 $P virality/<slug>/script.md --video edit/final.master.mp4 --schedule next_slot
```

## The gate (non-negotiable)

1. **Nothing posts until the user types "publish"** (or "post it", "schedule it") about this exact
   script and this exact video. A thumbs-up on the script is not a yes to posting.
2. Before the live run, always show the `--dry-run` output and the `--check` account names, and
   say which accounts it will post to. One Blotato workspace can hold several accounts on the same
   platform, so an id alone proves nothing.
3. YouTube defaults to `--privacy private`. Go public only when the user says so. A wrong-channel
   private upload is invisible and deletable; a public one notifies every subscriber.
4. The script must have no `{{your number}}` placeholders left. publish.py refuses if it does.

## Setup (once)

Keys go in `~/.claude/virality/.env` (mode 600, never in the repo):

```
BLOTATO_API_KEY=...
BLOTATO_ACCOUNT_INSTAGRAM=1234
BLOTATO_ACCOUNT_TIKTOK=1234
BLOTATO_ACCOUNT_YOUTUBE=1234
BLOTATO_ACCOUNT_FACEBOOK=1234
BLOTATO_FACEBOOK_PAGE_ID=...
BLOTATO_ACCOUNT_LINKEDIN=1234      # optional, and _TWITTER, _THREADS, _BLUESKY
```

Account ids come from Blotato (`--check` names them once they are set). Blotato is the posting
route because it uses each platform's official API on accounts the user connected themselves.
Nothing here logs in as the user.

## Run

1. `--check` with the platforms the user wants. Read the names back to them.
2. `--dry-run`. Read the payloads: the caption, the YouTube title, TikTok's settings, and the DM
   automation body if `--dm-url` is set.
3. Fix what it refuses. It refuses rather than truncates: over a platform's text limit, more than
   5 Instagram hashtags, a YouTube title over 100 characters, a missing TITLE line. Use
   `--text twitter=short.txt` for a platform that needs its own shorter text, or drop that platform.
4. After "publish": the live run. It prints PUBLISHED / SCHEDULED / FAILED per platform with the
   public URL, and exits 1 if anything did not land. Never stop while a post is still processing.
   If one is still pending after `--max-wait`, give the user the submission id.

Default platforms are `instagram,tiktok,youtube`. Add `facebook,linkedin,twitter,threads,bluesky`
as needed. LinkedIn uses the script's `## LinkedIn post` section when there is one.

## The keyword DM

`--dm-url URL` creates one Blotato DM automation per Instagram or Facebook account in
`--platforms`. It fires on a comment containing the keyword (sent as Title, UPPER and lower case)
on any post from that account, and sends `--dm-message` (default: a short "tap the button below"
line) with one button (`--dm-button`, 20 characters max) that opens the URL.

- **Existing keyword:** if the account already has a live automation for the same keyword (from an
  older video or another tool), publish.py leaves it alone and says what it sends. Rerun with
  `--dm-replace` to point it at the new link. That changes the DM for every post using that
  keyword, so ask first. A unique keyword per video avoids the question.
- **DM only:** `--dm-url URL --dm-only` sets up the automation without posting anything.
- **Instagram and Facebook only.** TikTok has no DM automation in Blotato. Say so when the user
  posts there with a comment CTA.
- **If no DMs arrive:** accounts connected to Blotato before its messaging launch must be
  reconnected in Blotato (Settings, Social Accounts) with the messaging permission ticked. Test
  from a different account: a comment from the connected account itself never triggers a run.

## After posting

Every post is one line in `~/.claude/virality/log.md`. A few days later, run
`python3 ~/.claude/skills/virality/tools/results.py` to pull the views back in, then start the
next /virality run from those numbers (step 2, source 0).

## Limits

- Blotato decides what each platform accepts. If a platform changes its rules, the post fails with
  Blotato's error message. Report it word for word.
- Nothing here guarantees reach. It posts what the user approved, when they said so.
