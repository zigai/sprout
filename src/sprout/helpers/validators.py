from __future__ import annotations

import re
from urllib.parse import urlparse

from sprout.helpers.github import parse_github_repository_url
from sprout.prompt.validation import ValidatorAnswers

SSH_URL_PATTERN = re.compile(r"^git@[\w.-]+:[\w./-]+$")
NPM_PACKAGE_NAME_PATTERN = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*")
REPOSITORY_NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


def validate_github_repository_url(
    value: str,
    answers: ValidatorAnswers | None = None,
) -> tuple[bool, str | None]:
    """
    Validate a GitHub repository URL and return a `(valid, message)` pair.

    Args:
        value (str): Candidate GitHub repository URL. Leading and trailing whitespace is ignored.
        answers (ValidatorAnswers | None): Optional answers map for interface compatibility.
            This parameter is unused.
    """
    del answers

    url = value.strip()
    if not url:
        return True, None

    if parse_github_repository_url(url) is not None:
        return True, None

    return False, "Repository URL must be a GitHub repository URL."


def validate_npm_package_name(
    value: str,
    answers: ValidatorAnswers | None = None,
) -> tuple[bool, str | None]:
    """
    Validate an npm package name and return a `(valid, message)` pair.

    Args:
        value (str): Candidate npm package name. Leading and trailing whitespace is ignored.
        answers (ValidatorAnswers | None): Optional answers map for interface compatibility.
            This parameter is unused.
    """
    del answers

    name = value.strip()
    if not name:
        return False, "Package name is required."
    if not NPM_PACKAGE_NAME_PATTERN.fullmatch(name):
        return False, "Package name must be a valid lowercase npm package name."
    return True, None


def validate_repository_name(
    value: str,
    answers: ValidatorAnswers | None = None,
) -> tuple[bool, str | None]:
    """
    Validate a repository name and return a `(valid, message)` pair.

    Args:
        value (str): Candidate repository name. Leading and trailing whitespace is ignored.
        answers (ValidatorAnswers | None): Optional answers map for interface compatibility.
            This parameter is unused.
    """
    del answers

    name = value.strip()
    if not name:
        return False, "Repository name is required."
    if not REPOSITORY_NAME_PATTERN.fullmatch(name):
        return (
            False,
            "Repository name may only include letters, numbers, dots, underscores, and hyphens.",
        )
    return True, None


def validate_semver(
    value: str,
    answers: ValidatorAnswers | None = None,
) -> tuple[bool, str | None]:
    """
    Validate a strict `major.minor.patch` semantic version and return a `(valid, message)` pair.

    Args:
        value (str): Candidate version. Leading and trailing whitespace is ignored.
        answers (ValidatorAnswers | None): Optional answers map for interface compatibility.
            This parameter is unused.
    """
    del answers

    if SEMVER_PATTERN.fullmatch(value.strip()):
        return True, None

    return False, "Version must be a semantic version like 1.2.3."


def validate_repository_url(
    value: str,
    answers: ValidatorAnswers | None = None,
) -> tuple[bool, str | None]:
    """
    Validate a repository URL and return a `(valid, message)` pair.

    Args:
        value (str): Candidate repository URL. Leading and trailing whitespace is ignored.
        answers (ValidatorAnswers | None): Optional answers map for interface compatibility.
            This parameter is unused.
    """
    del answers

    url = value.strip()
    if not url:
        return True, None

    if SSH_URL_PATTERN.fullmatch(url):
        return True, None

    parsed = urlparse(url)
    if parsed.scheme in {"http", "https", "ssh"} and parsed.netloc and parsed.path:
        return True, None

    return False, "Repository URL must be an HTTP(S) or git@ SSH URL."


__all__ = [
    "NPM_PACKAGE_NAME_PATTERN",
    "REPOSITORY_NAME_PATTERN",
    "SEMVER_PATTERN",
    "SSH_URL_PATTERN",
    "validate_github_repository_url",
    "validate_npm_package_name",
    "validate_repository_name",
    "validate_repository_url",
    "validate_semver",
]
