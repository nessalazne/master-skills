# Master skills (Ness edition)

`skills/edit` `skills/virality` `skills/build` `skills/virality-publish`

**Edit** cuts the dead space, adds captions and dynamic visuals, and generates any type of stop motion. **Virality** finds what's working in your niche and rewrites it in your voice as a shoot-ready script. **Build** takes you from "I want a site that does X" to a live, tested site.

What's different from the original pack:

1. **Research fetches itself.** Virality's step 2 used to mean reading view counts off your phone and pasting them in. Now `fetch_youtube.py` pulls any channel's Shorts through the YouTube Data API, and `fetch_instagram.py` pulls the reels under a hashtag through Apify, each with the creator's median views so the outlier ranking works. `results.py` reads back the views on what you posted, so your next script starts from your own numbers.
2. **It posts, and the CTA works.** Jake's version stops at the script. `/virality-publish` posts the finished video to Instagram, TikTok and YouTube (plus Facebook, LinkedIn, X, Threads and Bluesky if you want) through [Blotato](https://blotato.com/?ref=ness). With `--dm-url`, everyone who comments your keyword on Instagram or Facebook gets a DM with your link. Nothing posts until you type "publish".
3. **A longer humanizer list.** The slop list gains 47 entries: vibrant, "let's dive in", "game changer", "I hope this helps", reflex follow bait, announcement openers and the rest of the Instagram caption tells. There's also a short checklist for the structural ones a regex can only flag.
4. **Fit to 58 seconds.** `/edit` gets `fit.py`: if the cut runs long, it speeds picture and sound up together, never more than 1.1x, and keeps the captions in sync. If that isn't enough, it stops and tells you which phrases to cut. It never trims the ending, because that's where your CTA is.

## Install

Paste this repo link into Claude and say `install skills`.

```
https://github.com/nessalazne/master-skills

install skills
```

Or do it yourself, in Claude Code:

```bash
git clone https://github.com/nessalazne/master-skills.git
cp -r master-skills/skills/* ~/.claude/skills/
```

Or as a plugin:

```
/plugin marketplace add nessalazne/master-skills
/plugin install master-skills
```

Then just ask: "edit this video", "make this go viral", "build me a site that...", "publish it". Or call them directly with `/edit`, `/virality`, `/build`, `/virality-publish`.

## Keys (optional)

Every skill works by paste with no keys at all. Keys turn on the fetching and the posting. Put them in `~/.claude/virality/.env`, never in the repo:

```
YOUTUBE_API_KEY=...            # free: console.cloud.google.com, enable YouTube Data API v3
APIFY_TOKEN=...                # Instagram fetch, about $0.16 per 30 reels on Apify's free plan
BLOTATO_API_KEY=...            # posting and the keyword DM
BLOTATO_ACCOUNT_INSTAGRAM=1234
BLOTATO_ACCOUNT_TIKTOK=1234
BLOTATO_ACCOUNT_YOUTUBE=1234
BLOTATO_ACCOUNT_FACEBOOK=1234  # plus BLOTATO_FACEBOOK_PAGE_ID=... for Facebook
```

Run `python3 ~/.claude/skills/virality-publish/publish.py --check` to see the name behind each account id before anything posts.

## The four

### /edit

Hand it a raw take. It cuts the dead space and filler without clipping words, fits the cut under 58 seconds, writes 1 to 3 word captions that sit in the safe zone instead of on your face, plans dynamic visuals that show the thing you're saying at the moment you say it, and turns frames or a live clip into stop motion in any style (clay, paper cut-out, bricks, sticky notes, pixel). Finishes the audio at -14 LUFS with no compression on the voice.

Built on [HyperFrames](https://github.com/heygen-com/hyperframes) (motion engine), [Remotion's agent skills](https://github.com/remotion-dev/skills) and [video-use](https://github.com/browser-use/video-use) (transcript-driven editing). Needs `ffmpeg`. Transcription uses `faster-whisper` if you have it installed, otherwise it takes a transcript you already have.

### /virality

Find the outliers in your niche (views as a multiple of each creator's own median, so one huge account doesn't drown out the signal), break down why they worked (hook formula, format, structure, CTA), rewrite the winner in your voice for your audience, score the hook, and hand you a shoot-ready script with on-screen text, visuals per beat, a caption and a comment-a-keyword CTA.

Fill in `templates/voice.md` once (or paste three of your own captions and say "write my voice file"). Everything reads it.

### /virality-publish

Posts the rendered video with the script's caption, hashtags and YouTube title, waits until every post is live or scheduled, and logs the links. YouTube uploads default to private until you say public. With your link, it sets up the comment-keyword DM on Instagram and Facebook. If that keyword already has a DM from another video, it leaves it alone unless you pass `--dm-replace`.

### /build

A one-page plain-English spec, the simplest stack that works, a real design direction before any code, small verified build steps, a real-browser QA pass at phone, tablet and desktop widths, then ship. `tools/sitecheck.py` crawls the result for broken links, missing alt text, missing meta tags and other things that quietly break a launch. Unchanged from Jake's version.

## The fine print

- Nobody can guarantee views. This raises the odds by copying structure from what's already working in your niche and rewriting it in your voice. Results depend on the idea, the delivery and the account.
- Nothing logs into your accounts or scrapes behind a login. Research data comes from the official YouTube API, Apify's public no-login scrapers, or what you paste. Posting goes through Blotato, which uses each platform's official API on accounts you connected yourself.
- Comment-keyword DMs run on Instagram and Facebook only. TikTok has no DM automation in Blotato.
- Tools are Python standard library only. Media tools need `ffmpeg` on your PATH.
- Tests: `python3 tests/test_ness.py` for this edition, plus Jake's suites in each `tools/` folder.

## Go deeper

Want to go further, like building these skills into your own app or customizing them for how your business works? Join the hub: [hub.digicuratoragency.com/join](https://hub.digicuratoragency.com/join).

For more on AI automation, watch the [Learn With Ness](https://www.youtube.com/@nessalazne) YouTube channel.

## Credits

Original pack by Jake Schincariol, [opusjake.ai](https://opusjake.ai): [Jakeschincariol/master-skills](https://github.com/Jakeschincariol/master-skills).

Edit: HyperFrames by HeyGen (Apache-2.0), Remotion agent skills by Remotion, video-use by Browser Use (MIT).
Virality: linkedin-agent-skill and youtube-agent-skill by Jake Schincariol (MIT).
Build: impeccable by Paul Bakaus (Apache-2.0), frontend-design by Anthropic (Apache-2.0), gstack by Garry Tan (MIT), superpowers by Jesse Vincent (MIT).

This edition is maintained by Ness Alazne, [builds.digicuratoragency.com](https://builds.digicuratoragency.com). The fetch tools come from her [youtube-agent-skill](https://github.com/nessalazne/youtube-agent-skill) and [instagram-agent-skill](https://github.com/nessalazne/instagram-agent-skill) editions (Instagram actor choices adapted from Serge Bulaev's [instagram-skills](https://github.com/sergebulaev/instagram-skills), MIT). The publisher is ported from the same Instagram edition.

## License

MIT
