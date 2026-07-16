"""Run SecScan across every public repo and aggregate the results.

This is the part of the card that isn't just GitHub's data about me: it's my
own scanner, running against my own code, reporting what it actually found.
The numbers it produces are a live benchmark of secscan itself.

Workaround: secscan's -root flag is applied to the file scan but ignored by
the history scan, which silently reports commits_scanned: 0. Until that's
fixed upstream we chdir into each clone instead of passing -root.
See: https://github.com/Zayan-Mohamed/secscan
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "cache" / "secscan.json"
CLONE_TIMEOUT_SECONDS = 300
SCAN_TIMEOUT_SECONDS = 600


@dataclass
class ScanResult:
    repos_scanned: int = 0
    repos_failed: int = 0
    files_scanned: int = 0
    commits_scanned: int = 0
    findings: int = 0
    findings_high: int = 0  # Confidence >= 0.9
    duration_ms: int = 0
    version: str = "unknown"
    scanned_at: str = ""
    # A repo whose history scan didn't run is not a repo that came back clean.
    # Without this the card would report coverage it never had.
    history_gaps: int = 0


def public_repos(login: str, token: str | None) -> list[str]:
    """Every non-fork, non-empty public repo clone URL for `login`."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    urls: list[str] = []
    page = 1
    while True:
        response = requests.get(
            f"https://api.github.com/users/{login}/repos",
            params={"per_page": 100, "page": page, "type": "owner"},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        for repo in batch:
            if repo["fork"] or repo["size"] == 0:
                continue
            urls.append(repo["clone_url"])
        page += 1
    return urls


def scan_one(clone_url: str, workdir: Path) -> dict | None:
    """Clone one repo with full history and scan it. None if anything fails."""
    name = clone_url.rstrip("/").split("/")[-1].removesuffix(".git")
    target = workdir / name

    try:
        subprocess.run(
            ["git", "clone", "--quiet", clone_url, str(target)],
            check=True,
            capture_output=True,
            timeout=CLONE_TIMEOUT_SECONDS,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    report = workdir / f"{name}.json"
    try:
        # cwd=target rather than -root: see module docstring.
        subprocess.run(
            [
                "secscan",
                "-history=true",
                "-quiet",
                "-json",
                str(report),
            ],
            cwd=target,
            check=False,
            capture_output=True,
            timeout=SCAN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None
    finally:
        shutil.rmtree(target, ignore_errors=True)

    if not report.exists():
        return None
    try:
        return json.loads(report.read_text())
    except json.JSONDecodeError:
        return None


def run(login: str, token: str | None) -> ScanResult:
    result = ScanResult(
        scanned_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    )

    with tempfile.TemporaryDirectory(prefix="secscan-") as tmp:
        workdir = Path(tmp)
        for url in public_repos(login, token):
            report = scan_one(url, workdir)
            if report is None:
                result.repos_failed += 1
                continue

            stats = report.get("stats", {})
            result.repos_scanned += 1
            result.files_scanned += stats.get("files_scanned", 0)
            result.commits_scanned += stats.get("commits_scanned", 0)
            result.findings += stats.get("findings_unique", 0)
            result.duration_ms += stats.get("scan_duration_ms", 0)
            result.version = report.get("version", result.version)

            if not stats.get("history_scanned"):
                result.history_gaps += 1

            for finding in report.get("findings") or []:
                if finding.get("confidence", 0) >= 0.9:
                    result.findings_high += 1

    return result


if __name__ == "__main__":
    login = os.environ.get("GITHUB_LOGIN", "Zayan-Mohamed")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("ACCESS_TOKEN")

    result = run(login, token)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(asdict(result), indent=2) + "\n")
    print(json.dumps(asdict(result), indent=2))
