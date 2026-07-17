"""Build dark_mode.svg and light_mode.svg.

Run by .github/workflows/card.yml on a schedule. Reads the secscan aggregate
written by scan_repos.py, measures GitHub via github_stats.py, and renders both
themes.

The identity block below is the only hand-written content on the card, and it
is limited to things that are true and stable. Everything with a number in it
is measured.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import github_stats
import render

ROOT = Path(__file__).resolve().parent.parent
SCAN_PATH = ROOT / "cache" / "secscan.json"

LOGIN = "Zayan-Mohamed"

# The only hand-written content on the card, and deliberately limited to things
# that are true, stable, and not measurable from an API. There is no language
# list here: that used to be typed out, and is now counted in bytes.
IDENTITY = {
    "os": "Linux",
    "host": "SLIIT — BSc (Hons) IT, Data Science",
    "kernel": "Software Engineer · DevOps · Open Source",
    "editor": "Neovim, VS Code",
}

CONTACT = [
    ("Location", "Colombo, Sri Lanka"),
    ("Email", "zayanmohamed.tech@gmail.com"),
    ("LinkedIn", "zayan-mohamed"),
    ("Portfolio", "portfolio-zayan.vercel.app"),
    ("Dev.to", "zayanmohamed"),
]

# How many repos the "Shipping" section lists. They are ranked by live star
# count, so the ordering maintains itself and cannot go stale.
TOP_REPO_COUNT = 5

# Long descriptions are truncated to keep the column from overflowing.
SUMMARY_CHARS = 30


def summarise(description: str, limit: int = SUMMARY_CHARS) -> str:
    text = " ".join(description.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def load_scan() -> dict:
    """Read the secscan aggregate, or fall back to an empty scan."""
    if not SCAN_PATH.exists():
        return {
            "version": "?",
            "repos": 0,
            "files": 0,
            "commits": 0,
            "duration_s": 0.0,
            "findings": 0,
            "findings_high": 0,
            "at": "never",
        }

    raw = json.loads(SCAN_PATH.read_text())

    # A repo whose history scan silently didn't run has not been cleared, and
    # the card must not imply otherwise.
    gaps = raw.get("history_gaps", 0)
    if gaps:
        print(f"warning: {gaps} repo(s) had no git-history coverage", file=sys.stderr)

    return {
        "version": raw.get("version", "?"),
        "repos": raw.get("repos_scanned", 0),
        "files": raw.get("files_scanned", 0),
        "commits": raw.get("commits_scanned", 0),
        "duration_s": raw.get("duration_ms", 0) / 1000,
        "findings": raw.get("findings", 0),
        "findings_high": raw.get("findings_high", 0),
        "at": raw.get("scanned_at", "unknown"),
    }


def main() -> None:
    token = os.environ.get("ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("Set ACCESS_TOKEN or GITHUB_TOKEN")

    stats = github_stats.collect(token, LOGIN)

    top = [
        {
            "name": repo.name,
            "stars": repo.stars,
            "summary": summarise(repo.description),
        }
        for repo in stats.top_repos[:TOP_REPO_COUNT]
    ]

    data = {
        "login": f"{LOGIN.lower()}@colombo",
        "uptime": github_stats.uptime(stats.first_commit),
        "repos": top,
        "languages": render.language_chart(stats.languages),
        "language_total": render.human_bytes(sum(stats.languages.values())),
        "scan": load_scan(),
        "contact": CONTACT,
        "stats": {
            "repos": stats.repos,
            "stars": stats.stars,
            "commits": stats.commits,
            "followers": stats.followers,
            "loc": stats.loc,
            "additions": stats.additions,
            "deletions": stats.deletions,
        },
        **IDENTITY,
    }

    here = Path(__file__).resolve().parent
    for filename, palette, art in (
        ("dark_mode.svg", render.DARK, "portrait-dark.ans"),
        ("light_mode.svg", render.LIGHT, "portrait-light.ans"),
    ):
        portrait = render.parse_ans(here / art)
        (ROOT / filename).write_text(render.render(data, palette, portrait))
        print(f"wrote {filename}")


if __name__ == "__main__":
    main()
