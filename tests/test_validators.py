from __future__ import annotations

import pytest

from sprout.validators import validate_repository_url


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://github.com/zigai/sprout",
        "http://example.com/project",
        "ssh://example.com/repo.git",
        "git@github.com:zigai/sprout.git",
    ],
)
def test_validate_repository_url_accepts_supported_forms(value: str) -> None:
    valid, message = validate_repository_url(value)

    assert valid is True
    assert message is None


@pytest.mark.parametrize(
    "value",
    [
        "ftp://example.com/repo",
        "just-text",
        "https://",
        "git@github.com",
        "github.com/owner/repo",
    ],
)
def test_validate_repository_url_rejects_invalid_forms(value: str) -> None:
    valid, message = validate_repository_url(value)

    assert valid is False
    assert message == "Repository URL must be an HTTP(S) or git@ SSH URL."
