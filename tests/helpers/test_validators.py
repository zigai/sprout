from __future__ import annotations

import pytest

from sprout.helpers import (
    validate_github_repository_url,
    validate_npm_package_name,
    validate_repository_name,
    validate_semver,
)
from sprout.helpers.validators import validate_repository_url


@pytest.mark.parametrize(
    ("validator", "valid", "invalid"),
    [
        (validate_npm_package_name, "@scope/demo-package", "Demo Package"),
        (validate_repository_name, "demo.project_1", "demo/project"),
        (validate_semver, "1.2.3", "1.2"),
        (
            validate_github_repository_url,
            "https://github.com/zigai/demo",
            "https://example.com/demo",
        ),
    ],
)
def test_common_validators_accept_valid_values_and_reject_invalid_values(
    validator,
    valid: str,
    invalid: str,
) -> None:
    assert validator(valid) == (True, None)

    invalid_result, invalid_message = validator(invalid)

    assert invalid_result is False
    assert invalid_message


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a" * 214, True),
        ("a" * 215, False),
        ("@scope/" + "a" * 207, True),
        ("@scope/" + "a" * 208, False),
        ("node_modules", False),
        ("favicon.ico", False),
    ],
    ids=[
        "length-214",
        "length-215",
        "scoped-214",
        "scoped-215",
        "reserved-directory",
        "reserved-file",
    ],
)
def test_validate_npm_package_name_enforces_length_and_reserved_names(
    value: str,
    expected: bool,
) -> None:
    valid, message = validate_npm_package_name(value)

    assert valid is expected

    if expected:
        assert message is None
    else:
        assert message


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
