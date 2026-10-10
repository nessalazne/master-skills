# Humanizer pass (Ness edition)

`humanize.py` fixes what a regex can fix: invisible characters, dashes and the slop lexicon in
`tools/slop.json`. It only FLAGS the structural tells, because those need a rewrite, not a swap.
This is the checklist for that rewrite. Run it on every SAY line, the caption and any secondary
LinkedIn or long-form copy before the script is called shoot-ready.

## Rewrite these by hand

1. **"Not X, it's Y" frames.** "It's not just a tool, it's a system." Say the one thing you mean.
   Same for "not only... but also" and clipped endings like ", no guessing".
2. **Announcement openers.** "Let's dive in", "In this video I'm going to show you", "Today I want
   to talk about". The hook is the first line. Start there.
3. **Forced groups of three.** "Faster, cheaper, better." If there are really two things, say two.
   If there are four, say four.
4. **Stock AI words.** delve, vibrant, testament, landscape, pivotal, crucial, seamless, robust,
   game changer. The lexicon swaps most of them; read the swap out loud and fix the ones that
   now sound flat.
5. **Sales language.** "Revolutionary", "unlock", "supercharge", "the ultimate". Replace the
   adjective with the number from the proof bank, or cut it.
6. **Chatbot leftovers.** "I hope this helps", "Great question", "Let me know if you want me to",
   "Here's a breakdown". None of these belong in a script.
7. **Vague sources.** "Experts say", "studies show". Name the source or drop the claim.
8. **Dashes.** No em or en dashes anywhere. `humanize.py` turns them into commas, which can leave a
   comma splice. Read the line and make it two sentences if it needs to be.

## Keep these

- Every fact, number and name. The pass changes how a line sounds, never what it claims.
- The user's own habits from `voice.md`: their contractions, slang, sentence length and the
  phrases they repeat on purpose. A voice sample beats every rule on this page.
- The CTA line exactly as planned (`Comment KEYWORD and I'll send you ...`). The lexicon strips
  reflex bait like "follow for more", not a real keyword ask.

## Then measure

```bash
python3 tools/humanize.py virality/<slug>/draft.txt --report -o virality/<slug>/clean.txt
python3 tools/detect.py virality/<slug>/draft.txt virality/<slug>/clean.txt
```

Fix every flagged structure, re-run `detect.py`, and aim for PASS. It is a local heuristic, not a
detector API. Never tell anyone their text is "undetectable".
