from __future__ import annotations

from types import ModuleType

import pytest

from sprout.cli import _manifest_skip


def test_manifest_skip_accepts_two_positional_args() -> None:
    module = ModuleType("test_manifest")

    def should_skip_file(relative_path: str, answers: dict[str, object]) -> bool:
        return False

    module.should_skip_file = should_skip_file

    skip = _manifest_skip(module)

    assert skip is should_skip_file


def test_manifest_skip_rejects_non_callable() -> None:
    module = ModuleType("test_manifest")
    module.should_skip_file = "not-a-function"

    with pytest.raises(SystemExit, match="must be a callable"):
        _manifest_skip(module)


def test_manifest_skip_rejects_wrong_arity() -> None:
    module = ModuleType("test_manifest")

    def should_skip_file(relative_path: str) -> bool:
        return False

    module.should_skip_file = should_skip_file

    with pytest.raises(SystemExit, match="must accept exactly two positional parameters"):
        _manifest_skip(module)


def test_manifest_skip_rejects_keyword_only_signature() -> None:
    module = ModuleType("test_manifest")

    def should_skip_file(*, relative_path: str, answers: dict[str, object]) -> bool:
        return False

    module.should_skip_file = should_skip_file

    with pytest.raises(SystemExit, match="must accept exactly two positional parameters"):
        _manifest_skip(module)
