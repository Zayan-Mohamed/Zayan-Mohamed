"""Collect GitHub statistics for the profile card.

Every number the card prints is measured here. Nothing is hand-written, so a
stat can only be wrong if the API is wrong or this module has a bug -- never
because someone forgot to update a string.

The lines-of-code walk is the expensive part: it pages through the commit
history of every repo the user has touched. Results are cached per repo and
keyed on the history's totalCount, so an untouched repo costs one cheap query
on subsequent runs instead of a full re-walk.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import requests

API_URL = "https://api.github.com/graphql"
CACHE_PATH = Path(__file__).resolve().parent.parent / "cache" / "loc_cache.json"

# GitHub's secondary rate limiter is unhappy with bursts of history queries.
# A small pause between repos keeps a full cold run under the limit.
REPO_QUERY_DELAY_SECONDS = 0.25


class GitHubError(RuntimeError):
    """Raised when the GraphQL API returns something we can't use."""


@dataclass
class Repo:
    name_with_owner: str
    stars: int
    is_private: bool
    has_commits: bool
    description: str = ""
    languages: dict[str, int] = field(default_factory=dict)

    @property
    def owner(self) -> str:
        return self.name_with_owner.split("/", 1)[0]

    @property
    def name(self) -> str:
        return self.name_with_owner.split("/", 1)[1]


@dataclass
class Stats:
    login: str
    repos: int = 0
    contributed: int = 0
    stars: int = 0
    followers: int = 0
    commits: int = 0
    additions: int = 0
    deletions: int = 0
    first_commit: datetime | None = None
    top_repos: list[Repo] = field(default_factory=list)
    # Bytes of source per language, summed across every non-fork repo. This is
    # the same measure GitHub's own language bar uses, so vendored and
    # generated files are already excluded by linguist.
    languages: dict[str, int] = field(default_factory=dict)

    @property
    def loc(self) -> int:
        return self.additions - self.deletions


class GitHubClient:
    def __init__(self, token: str, login: str) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"bearer {token}",
                "Content-Type": "application/json",
            }
        )
        self.login = login

    def query(self, document: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Run one GraphQL query, retrying on rate limits and transient 5xx."""
        for attempt in range(5):
            try:
                response = self._session.post(
                    API_URL,
                    json={"query": document, "variables": variables},
                    timeout=30,
                )
            except requests.RequestException:
                # A dropped connection is as transient as a 502, and a long
                # lines-of-code walk gives it plenty of chances to happen.
                # Failing here would leave the card stale with no explanation.
                if attempt == 4:
                    raise
                time.sleep(2**attempt)
                continue

            if response.status_code in (502, 503, 504):
                time.sleep(2**attempt)
                continue

            if response.status_code == 403:
                # Secondary rate limit. Honour Retry-After when present.
                wait = int(response.headers.get("Retry-After", 2**attempt))
                time.sleep(wait)
                continue

            if response.status_code != 200:
                raise GitHubError(
                    f"HTTP {response.status_code} from GraphQL API: {response.text[:200]}"
                )

            payload = response.json()
            if "errors" in payload:
                raise GitHubError(f"GraphQL errors: {payload['errors']}")
            return payload["data"]

        raise GitHubError("GraphQL API did not succeed after 5 attempts")


USER_QUERY = """
query($login: String!) {
  user(login: $login) {
    id
    followers { totalCount }
  }
}
"""

REPOS_QUERY = """
query($login: String!, $cursor: String, $affiliations: [RepositoryAffiliation]) {
  user(login: $login) {
    repositories(
      first: 100
      after: $cursor
      ownerAffiliations: $affiliations
      isFork: false
      orderBy: { field: STARGAZERS, direction: DESC }
    ) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        stargazerCount
        isPrivate
        description
        defaultBranchRef { name }
        languages(first: 10, orderBy: { field: SIZE, direction: DESC }) {
          edges {
            size
            node { name }
          }
        }
      }
    }
  }
}
"""

HISTORY_QUERY = """
query($owner: String!, $name: String!, $cursor: String, $id: ID) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $cursor, author: { id: $id }) {
            totalCount
            pageInfo { hasNextPage endCursor }
            nodes { committedDate additions deletions }
          }
        }
      }
    }
  }
}
"""


def _iter_repos(
    client: GitHubClient, affiliations: list[str]
) -> Iterator[tuple[Repo, int]]:
    """Yield (repo, total_count) for every non-fork repo under `affiliations`."""
    cursor = None
    while True:
        data = client.query(
            REPOS_QUERY,
            {"login": client.login, "cursor": cursor, "affiliations": affiliations},
        )
        block = data["user"]["repositories"]
        for node in block["nodes"]:
            yield (
                Repo(
                    name_with_owner=node["nameWithOwner"],
                    stars=node["stargazerCount"],
                    is_private=node["isPrivate"],
                    has_commits=node["defaultBranchRef"] is not None,
                    description=node.get("description") or "",
                    languages={
                        edge["node"]["name"]: edge["size"]
                        for edge in (node.get("languages") or {}).get("edges", [])
                    },
                ),
                block["totalCount"],
            )
        if not block["pageInfo"]["hasNextPage"]:
            return
        cursor = block["pageInfo"]["endCursor"]


def _load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except json.JSONDecodeError:
        # A corrupt cache should cost us a slow run, not a failed one.
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")


def _walk_history(
    client: GitHubClient, repo: Repo, user_id: str
) -> dict[str, Any]:
    """Page through one repo's history, summing the user's own commits."""
    cursor = None
    commits = 0
    additions = 0
    deletions = 0
    earliest: str | None = None
    total = 0

    while True:
        data = client.query(
            HISTORY_QUERY,
            {
                "owner": repo.owner,
                "name": repo.name,
                "cursor": cursor,
                "id": user_id,
            },
        )
        branch = data["repository"]["defaultBranchRef"]
        if branch is None:
            break

        history = branch["target"]["history"]
        total = history["totalCount"]
        for node in history["nodes"]:
            commits += 1
            additions += node["additions"]
            deletions += node["deletions"]
            if earliest is None or node["committedDate"] < earliest:
                earliest = node["committedDate"]

        if not history["pageInfo"]["hasNextPage"]:
            break
        cursor = history["pageInfo"]["endCursor"]

    return {
        "total": total,
        "commits": commits,
        "additions": additions,
        "deletions": deletions,
        "earliest": earliest,
    }


def _history_total(client: GitHubClient, repo: Repo, user_id: str) -> int:
    """Cheap single query for just the commit count, used as a cache key."""
    data = client.query(
        HISTORY_QUERY,
        {"owner": repo.owner, "name": repo.name, "cursor": None, "id": user_id},
    )
    branch = data["repository"]["defaultBranchRef"]
    if branch is None:
        return 0
    return branch["target"]["history"]["totalCount"]


def collect(token: str, login: str) -> Stats:
    """Measure everything the card needs."""
    client = GitHubClient(token, login)

    user = client.query(USER_QUERY, {"login": login})["user"]
    user_id = user["id"]

    stats = Stats(login=login, followers=user["followers"]["totalCount"])
    cache = _load_cache()

    owned: list[Repo] = []
    contributed_count = 0

    for repo, total in _iter_repos(client, ["OWNER"]):
        owned.append(repo)
        stats.stars += repo.stars
        stats.repos = total

    for repo, total in _iter_repos(
        client, ["COLLABORATOR", "ORGANIZATION_MEMBER"]
    ):
        owned.append(repo)
        contributed_count = total

    stats.contributed = contributed_count

    seen: set[str] = set()
    for repo in owned:
        if repo.name_with_owner in seen or not repo.has_commits:
            continue
        seen.add(repo.name_with_owner)

        cached = cache.get(repo.name_with_owner)
        total = _history_total(client, repo, user_id)

        if cached is not None and cached.get("total") == total:
            entry = cached
        else:
            entry = _walk_history(client, repo, user_id)
            cache[repo.name_with_owner] = entry
            time.sleep(REPO_QUERY_DELAY_SECONDS)

        stats.commits += entry["commits"]
        stats.additions += entry["additions"]
        stats.deletions += entry["deletions"]

        if entry["earliest"]:
            moment = datetime.fromisoformat(
                entry["earliest"].replace("Z", "+00:00")
            )
            if stats.first_commit is None or moment < stats.first_commit:
                stats.first_commit = moment

    _save_cache(cache)

    for repo in owned:
        if repo.is_private:
            continue
        for language, size in repo.languages.items():
            stats.languages[language] = stats.languages.get(language, 0) + size

    stats.top_repos = sorted(
        (r for r in owned if not r.is_private),
        key=lambda r: r.stars,
        reverse=True,
    )
    return stats


def uptime(since: datetime | None) -> str:
    """Render a duration as neofetch-style uptime, counting from `since`."""
    if since is None:
        return "unknown"

    now = datetime.now(timezone.utc)
    years = now.year - since.year
    months = now.month - since.month
    days = now.day - since.day

    if days < 0:
        months -= 1
        # Days in the month that just ended, relative to now.
        previous_month = now.month - 1 or 12
        previous_year = now.year if now.month > 1 else now.year - 1
        if previous_month in (1, 3, 5, 7, 8, 10, 12):
            days += 31
        elif previous_month in (4, 6, 9, 11):
            days += 30
        else:
            leap = previous_year % 4 == 0 and (
                previous_year % 100 != 0 or previous_year % 400 == 0
            )
            days += 29 if leap else 28
    if months < 0:
        years -= 1
        months += 12

    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if months:
        parts.append(f"{months} month{'s' if months != 1 else ''}")
    parts.append(f"{days} day{'s' if days != 1 else ''}")
    return ", ".join(parts)


if __name__ == "__main__":
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("ACCESS_TOKEN")
    if not token:
        raise SystemExit("Set GITHUB_TOKEN or ACCESS_TOKEN")
    result = collect(token, os.environ.get("GITHUB_LOGIN", "Zayan-Mohamed"))
    print(json.dumps({
        "repos": result.repos,
        "contributed": result.contributed,
        "stars": result.stars,
        "followers": result.followers,
        "commits": result.commits,
        "additions": result.additions,
        "deletions": result.deletions,
        "loc": result.loc,
        "uptime": uptime(result.first_commit),
        "top": [(r.name_with_owner, r.stars) for r in result.top_repos[:5]],
    }, indent=2))
