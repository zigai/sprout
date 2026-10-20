from __future__ import annotations

from pathlib import Path

import pytest

from sprout.display import shorten_home


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/home/user", "~"),
        (Path("/home/user/projects/demo"), "~/projects/demo"),
        ("Generating a project in /home/user/demo now", "Generating a project in ~/demo now"),
        ("'/home/user/demo' and /home/user", "'~/demo' and ~"),
        ("/home/user2/demo", "/home/user2/demo"),
        ("/home/user.old/demo", "/home/user.old/demo"),
        ("/srv/home/user/demo", "/srv/home/user/demo"),
        ("/opt/demo", "/opt/demo"),
    ],
)
def test_shorten_home_replaces_only_whole_home_prefix(
    monkeypatch: pytest.MonkeyPatch,
    text: str | Path,
    expected: str,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: Path("/home/user"))

    assert shorten_home(text) == expected
