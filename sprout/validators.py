from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from urllib.parse import urlparse

from sprout.project.validators import (
    NPM_PACKAGE_NAME_PATTERN,
    REPOSITORY_NAME_PATTERN,
    SEMVER_PATTERN,
    validate_github_repository_url,
    validate_npm_package_name,
    validate_repository_name,
    validate_semver,
)

type ValidationResult = tuple[bool, str | None]
type ValidatorAnswers = Mapping[str, object]

ValidatorFn = Callable[[str], ValidationResult]
ContextValidatorFn = Callable[[str, ValidatorAnswers], ValidationResult]
ValidatorType = ValidatorFn | ContextValidatorFn

SSH_URL_PATTERN = re.compile(r"^git@[\w.-]+:[\w./-]+$")


def validate_repository_url(
    value: str,
    _answers: ValidatorAnswers | None = None,
) -> tuple[bool, str | None]:
    """
    Validate a repository URL and return a `(valid, message)` pair.

    Args:
        value (str): Candidate repository URL. Leading and trailing whitespace is ignored.
        _answers (ValidatorAnswers | None): Optional answers map for interface compatibility.
            This parameter is unused.
    """
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
    "ContextValidatorFn",
    "ValidationResult",
    "ValidatorAnswers",
    "ValidatorFn",
    "ValidatorType",
    "validate_github_repository_url",
    "validate_npm_package_name",
    "validate_repository_name",
    "validate_repository_url",
    "validate_semver",
]
