from __future__ import annotations

import textwrap
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

import pytest


class MakeTemplate(Protocol):
    def __call__(
        self,
        manifest_source: str,
        files: Mapping[str, str] | None = None,
    ) -> Path: ...


@pytest.fixture
def make_template(tmp_path: Path) -> MakeTemplate:
    counter = 0

    def _make(
        manifest_source: str,
        files: Mapping[str, str] | None = None,
    ) -> Path:
        nonlocal counter
        counter += 1

        root = tmp_path / f"template_{counter}"
        root.mkdir()
        (root / "sprout.py").write_text(
            textwrap.dedent(manifest_source).lstrip(),
            encoding="utf-8",
        )

        template_files = (
            dict(files)
            if files is not None
            else {"template/README.md.jinja": "name={{ name|default('demo') }}\n"}
        )
        for relative, content in template_files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")

        return root

    return _make
