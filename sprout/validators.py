from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlparse

ValidatorFn = Callable[[str], tuple[bool, str | None]]
ValidatorType = Callable[..., tuple[bool, str | None]]

SSH_URL_PATTERN = re.compile(r"^git@[\w.-]+:[\w./-]+$")


def validate_repository_url(
    value: str,
    _answers: Mapping[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """
    Validate a repository URL and return a `(valid, message)` pair.

    Args:
        value (str): Candidate repository URL. Leading and trailing whitespace is ignored.
        _answers (Mapping[str, Any] | None): Optional answers map for interface compatibility.
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
    "ValidatorFn",
    "ValidatorType",
    "validate_repository_url",
]
