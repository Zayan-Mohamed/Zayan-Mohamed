# The card

The README is one `<picture>` element. Everything you see on it is generated
here and committed back by [`card.yml`](../.github/workflows/card.yml) once a
day.

The rule this is built on: **nothing on the card is typed by hand.** Every
number is measured by something, and if a number is wrong the bug is in the
thing that measured it. There are no skill bars, no percentages, no rounded
"1k+ commits" — those can't be checked, so they don't belong on a profile.

| | |
|---|---|
| [`github_stats.py`](github_stats.py) | GitHub GraphQL: repos, stars, followers, commits, and a lines-of-code walk over every repo's history. Cached per repo on the history's `totalCount`, so an untouched repo costs one cheap query instead of a full re-walk. |
| [`scan_repos.py`](scan_repos.py) | Clones every public repo and runs [secscan](https://github.com/Zayan-Mohamed/secscan) over the working tree and the full git history. |
| [`render.py`](render.py) | Both themes from one template, so they can't drift apart. Geometry is derived from the art and column width rather than hardcoded. |
| [`build.py`](build.py) | Wires the above together and writes the two SVGs. |

## Uptime

Counts from the earliest commit found during the lines-of-code walk, so it
costs nothing extra and ticks up on its own.

## Shipping

Ranked by live star count. The ordering maintains itself — nothing to update
when a project takes off.

## The secscan section

The scanner is mine, so the card runs it against my own code every day and
publishes whatever it finds. That's the part I can't fake: the scan is a public,
daily benchmark of a tool I wrote, on a corpus anyone can clone and re-run.

It reports raw findings and the count at `>=0.9` confidence, because those are
mechanical facts. It does not claim "0 secrets" — that would be a human
judgement about triage, and a number a script can't honestly maintain.

Building this is what surfaced the bugs fixed in
[secscan v2.2.3](https://github.com/Zayan-Mohamed/secscan/blob/main/CHANGELOG.md):
`-root` was ignored by the history scanner, so every CI user silently got no
history coverage; entropy detection was mathematically incapable of firing on a
real credential; and deduplication across commits could never fire. Pointing the
tool at my own code found them in an afternoon. False positives went from 475 to
20 on this corpus, with no loss of recall.

## Running it locally

```bash
pip install requests
go install github.com/Zayan-Mohamed/secscan/v2@v2.2.3

GITHUB_TOKEN=$(gh auth token) python card/scan_repos.py   # writes cache/secscan.json
GITHUB_TOKEN=$(gh auth token) python card/build.py        # writes the SVGs
```

A cold lines-of-code walk takes a few minutes; after that the cache makes it
quick.
