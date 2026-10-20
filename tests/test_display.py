from __future__ import annotations

import os
from pathlib import Path

import pytest

from sprout.display import shorten_home


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("{home}", "~"),
        (Path("/home/user/projects/demo"), "~{sep}projects{sep}demo"),
        ("Generating a project in {home}{sep}demo now", "Generating a project in ~{sep}demo now"),
        ("'{home}{sep}demo' and {home}", "'~{sep}demo' and ~"),
        ("{home}2{sep}demo", "{home}2{sep}demo"),
        ("{home}.old{sep}demo", "{home}.old{sep}demo"),
        ("{sep}srv{home}{sep}demo", "{sep}srv{home}{sep}demo"),
        ("{sep}opt{sep}demo", "{sep}opt{sep}demo"),
    ],
)
def test_shorten_home_replaces_only_whole_home_prefix(
    monkeypatch: pytest.MonkeyPatch,
    text: str | Path,
    expected: str,
) -> None:
    home = Path("/home/user")
    monkeypatch.setattr(Path, "home", lambda: home)
    placeholders = {"home": str(home), "sep": os.sep}
    if isinstance(text, str):
        text = text.format_map(placeholders)

    assert shorten_home(text) == expected.format_map(placeholders)
