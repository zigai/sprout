from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

GITHUB_REPOSITORY_PATTERN = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)
GITHUB_SSH_REPOSITORY_PATTERN = re.compile(
    r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$"
)
GITHUB_SSH_URL_REPOSITORY_PATTERN = re.compile(
    r"^ssh://git@github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)


@dataclass(frozen=True)
class GitHubRepository:
    owner: str
    name: str

    @property
    def install_source(self) -> str:
        return f"github.com/{self.owner}/{self.name}"

    @property
    def target(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def url(self) -> str:
        return github_repository_url(self.owner, self.name)

    @property
    def git_url(self) -> str:
        return f"git+{self.url}.git"


def github_repository_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}"


def parse_github_repository_url(value: str) -> GitHubRepository | None:
    cleaned = value.strip()
    for pattern in (
        GITHUB_REPOSITORY_PATTERN,
        GITHUB_SSH_REPOSITORY_PATTERN,
        GITHUB_SSH_URL_REPOSITORY_PATTERN,
    ):
        match = pattern.fullmatch(cleaned)
        if match is None:
            continue

        return GitHubRepository(owner=match.group("owner"), name=match.group("repo"))

    return None


def is_github_repository_url(value: str | None) -> bool:
    return isinstance(value, str) and parse_github_repository_url(value) is not None


def github_repository_target(
    answers: Mapping[str, object],
    *,
    repository_url_key: str = "repository_url",
    repo_name_key: str = "repo_name",
    fallback_repo_name: str = "project",
) -> str:
    repository_url = str(answers.get(repository_url_key) or "").strip()
    repository = parse_github_repository_url(repository_url)
    if repository is not None:
        return repository.target

    repo_name = str(answers.get(repo_name_key) or "").strip()

    return repo_name or fallback_repo_name


def repository_git_url(url: str) -> str:
    cleaned = url.rstrip("/")
    if cleaned.startswith("git+"):
        return cleaned

    repository = parse_github_repository_url(cleaned)
    if repository is not None:
        return repository.git_url

    return f"git+{cleaned}"


def github_install_source(url: str, *, fallback: str | None = None) -> str:
    repository = parse_github_repository_url(url)
    if repository is not None:
        return repository.install_source

    return fallback if fallback is not None else url.strip()


__all__ = [
    "GITHUB_REPOSITORY_PATTERN",
    "GITHUB_SSH_REPOSITORY_PATTERN",
    "GITHUB_SSH_URL_REPOSITORY_PATTERN",
    "GitHubRepository",
    "github_install_source",
    "github_repository_target",
    "github_repository_url",
    "is_github_repository_url",
    "parse_github_repository_url",
    "repository_git_url",
]
