#!/usr/bin/env python3
"""fit.py - get a cut under the Shorts length cap without chopping the ending.

Ness edition. New in this fork. The strategy comes from Ness's shorten-audio skill (silence
first, then a gentle speed-up, never more than 1.1x) applied to video after deadspace.py:

    python3 fit.py edit/take.cut.mp4 --words edit/take.cut.words.json -o edit/take.fit.mp4
    python3 fit.py edit/take.cut.mp4 --words edit/take.cut.words.json --dry-run
    python3 fit.py edit/take.cut.mp4 --target 45 --max-speed 1.08 -o edit/take.fit.mp4

What it does, in order:
  1. Already at or under --target (default 58 s)? Copies it through untouched.
  2. Over by more than --max-speed can absorb? Stops with exit 1 and prints the longest middle
     phrases as cut candidates (hook and CTA are never suggested). Cut them in the EDL, or rerun
     deadspace.py with --pace tight, then run fit.py again.
  3. Otherwise speeds picture and sound up together (setpts + atempo, pitch kept) by the smallest
     factor that fits, and rescales the word timings so captions.py lines up on the new cut.

It never trims the end to make the number. The CTA lives there.

Writes <out>.mp4, <out>.words.json (the rescaled timings, when --words is given) and
<out>.phrases.txt. Python 3 standard library + ffmpeg.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mediakit as mk  # noqa: E402

SAFETY = 0.15   # seconds of headroom under the target, so frame rounding cannot push it over


def speed_needed(duration: float, target: float) -> float:
    """The smallest speed-up that lands at or under target (1.0 when it already fits)."""
    if duration <= target:
        return 1.0
    return duration / max(target - SAFETY, 0.1)


def rescale_words(words: list, speed: float) -> list:
    out = []
    for w in words:
        item = dict(w)
        item["start"] = w["start"] / speed
        item["end"] = w["end"] / speed
        out.append(item)
    return out


def cut_candidates(words: list, top: int = 5) -> list:
    """The longest phrases between the hook and the CTA, longest first: [(seconds, line)]."""
    lines = mk.phrase_lines(words)
    middle = lines[1:-1] if len(lines) > 2 else []
    scored = []
    for line in middle:
        stamp = line[1:line.index("]")]
        start, end = (float(x) for x in stamp.split("-"))
        scored.append((end - start, line))
    scored.sort(key=lambda x: -x[0])
    return scored[:top]


def build_filters(speed: float, has_video: bool, has_audio: bool) -> tuple:
    parts, maps = [], []
    if has_video:
        parts.append(f"[0:v]setpts=PTS/{speed:.6f}[v]")
        maps += ["-map", "[v]"]
    if has_audio:
        parts.append(f"[0:a:0]atempo={speed:.6f}[a]")
        maps += ["-map", "[a]"]
    return ";".join(parts), maps


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=mk.EXIT_CODES_HELP)
    ap.add_argument("input", help="the cut video (deadspace.py output)")
    ap.add_argument("-o", "--output", help="output video (default <input>.fit.mp4)")
    ap.add_argument("--words", help="word timings on the input's timeline (<name>.cut.words.json)")
    ap.add_argument("--target", type=float, default=58.0, help="length cap in seconds (default 58)")
    ap.add_argument("--max-speed", type=float, default=1.1,
                    help="most speed-up allowed (default 1.1; above that a voice sounds rushed)")
    ap.add_argument("--dry-run", action="store_true", help="report the plan, write nothing")
    a = ap.parse_args()

    if a.target <= 1:
        raise mk.EditError("--target must be more than 1 second", mk.EXIT_USAGE)
    if not 1.0 <= a.max_speed <= 1.5:
        raise mk.EditError("--max-speed must be between 1.0 and 1.5", mk.EXIT_USAGE)

    info = mk.probe(a.input)
    duration = info["end"] or info["duration"] or 0
    if not duration:
        raise mk.EditError(f"cannot read a duration from {a.input}", mk.EXIT_USAGE)
    words = mk.load_words(a.words, duration) if a.words else None
    out = a.output or mk.default_output(a.input, ".fit", ".mp4")
    out_words = mk.default_output(out, "", ".words.json")
    out_phrases = mk.default_output(out, "", ".phrases.txt")
    speed = speed_needed(duration, a.target)

    print(f"{os.path.basename(a.input)}: {mk.fmt_time(duration)} ({duration:.2f}s), target {a.target:g}s")

    if speed > a.max_speed:
        at_max = duration / a.max_speed
        print(f"\nDoes not fit. At {a.max_speed:g}x it is still {at_max:.2f}s, "
              f"{at_max - a.target:.2f}s over. Nothing was written.")
        print("Cut first, then rerun fit.py:")
        print("  - rerun deadspace.py with --pace tight (shorter pauses), or")
        print("  - veto or add cuts in the EDL and render with --from-edl.")
        if words:
            print(f"\nLongest middle phrases (hook and CTA left out), seconds on the input timeline:")
            for secs, line in cut_candidates(words):
                print(f"  {secs:5.2f}s  {line}")
        else:
            print("\nPass --words <name>.cut.words.json to get a list of phrases worth cutting.")
        return mk.EXIT_FAIL

    if speed == 1.0:
        print("Already fits. Copied through unchanged.")
        if not a.dry_run:
            if os.path.abspath(out) != os.path.abspath(a.input):
                shutil.copyfile(a.input, out)
            if words:
                mk.save_words(out_words, words, source=out, engine="fit.py (unchanged)")
                with open(out_phrases, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(mk.phrase_lines(words)) + "\n")
        return mk.EXIT_OK

    new_len = duration / speed
    print(f"Speed-up {speed:.3f}x -> {new_len:.2f}s (pitch kept, picture and sound together)")
    if a.dry_run:
        print("Dry run: nothing written.")
        return mk.EXIT_OK

    video, audio = info["video"], info["audio"]
    graph, maps = build_filters(speed, bool(video), bool(audio))
    cmd = [mk.ffmpeg_bin(), "-hide_banner", "-y", "-i", a.input, "-filter_complex", graph] + maps
    if video:
        codec, note = mk.video_codec_args(video)
        rate = mk.cfr_rate(video)
        cmd += codec + ["-r", f"{rate.numerator}/{rate.denominator}"]
        print(f"video: {note}, {float(rate):.3f} fps")
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "256k", "-ar", "48000"]
    if video and audio:
        cmd += ["-shortest"]  # frame rounding can leave the picture a frame longer than the sound
    cmd += ["-movflags", "+faststart", out]
    mk.run(cmd)

    got = mk.probe(out)
    got_len = got["end"] or got["duration"] or 0
    if got_len > a.target + 0.05:
        mk.warn(f"output is {got_len:.2f}s, over the {a.target:g}s target; rerun with a lower --target")
    print(f"wrote {out} ({got_len:.2f}s)")
    if words:
        scaled = rescale_words(words, speed)
        mk.save_words(out_words, scaled, source=out, engine=f"fit.py x{speed:.4f}",
                      extra={"fit": {"speed": round(speed, 6), "source": os.path.abspath(a.input)}})
        with open(out_phrases, "w", encoding="utf-8") as fh:
            fh.write("\n".join(mk.phrase_lines(scaled)) + "\n")
        print(f"wrote {out_words} (timings / {speed:.4f}), use it for captions.py --words")
    return mk.EXIT_OK


if __name__ == "__main__":
    sys.exit(mk.run_main(main))
