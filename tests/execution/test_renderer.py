from __future__ import annotations

from pathlib import Path

import pytest

from sprout.errors import SproutGenerationError
from sprout.renderer import render_templates


def test_render_templates_renders_and_copies(tmp_path: Path) -> None:
    template_dir = tmp_path / "template"
    destination = tmp_path / "out"
    template_dir.mkdir()
    (template_dir / "README.md.jinja").write_text("Hello {{ name }}\n", encoding="utf-8")
    (template_dir / "plain.txt").write_text("static\n", encoding="utf-8")

    created = render_templates(
        None,
        template_dir,
        destination,
        {"name": "Sprout"},
    )

    assert (destination / "README.md").read_text(encoding="utf-8") == "Hello Sprout\n"
    assert (destination / "plain.txt").read_text(encoding="utf-8") == "static\n"
    assert Path("README.md") in created
    assert Path("plain.txt") in created


def test_render_templates_translates_destination_write_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    template_dir = tmp_path / "template"
    destination = tmp_path / "out"
    template_dir.mkdir()
    destination.mkdir()
    (template_dir / "README.md.jinja").write_text("Hello\n", encoding="utf-8")
    cause = OSError("platform-specific detail")

    def fail_write_text(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        del self, data, encoding, errors, newline
        raise cause

    monkeypatch.setattr(Path, "write_text", fail_write_text)

    with pytest.raises(SproutGenerationError) as raised:
        render_templates(None, template_dir, destination, {})

    assert str(raised.value) == "failed to write destination file 'README.md'."
    assert raised.value.__cause__ is cause


def test_render_templates_translates_destination_copy_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    template_dir = tmp_path / "template"
    destination = tmp_path / "out"
    template_dir.mkdir()
    destination.mkdir()
    (template_dir / "plain.txt").write_text("static\n", encoding="utf-8")
    cause = OSError("platform-specific detail")

    def fail_copy(
        source: str | Path,
        target: str | Path,
        *,
        follow_symlinks: bool = True,
    ) -> str:
        del source, target, follow_symlinks
        raise cause

    monkeypatch.setattr("sprout.renderer.shutil.copy2", fail_copy)

    with pytest.raises(SproutGenerationError) as raised:
        render_templates(None, template_dir, destination, {})

    assert str(raised.value) == "failed to copy destination file 'plain.txt'."
    assert raised.value.__cause__ is cause


def test_render_templates_supports_rendered_paths_and_skip(tmp_path: Path) -> None:
    template_dir = tmp_path / "template"
    destination = tmp_path / "out"
    template_dir.mkdir()
    destination.mkdir()
    (template_dir / "{{ package_name }}.txt.jinja").write_text(
        "{{ package_name }}\n", encoding="utf-8"
    )
    (template_dir / "skip-me.txt").write_text("skip\n", encoding="utf-8")
    (template_dir / "__pycache__").mkdir()
    (template_dir / "__pycache__" / "ignore.pyc").write_text("x", encoding="utf-8")
    (template_dir / "ignore.pyc").write_text("x", encoding="utf-8")

    seen: list[str] = []

    def skip(relative_path: str, _answers: dict[str, object]) -> bool:
        seen.append(relative_path)
        return relative_path == "skip-me.txt"

    created = render_templates(
        None,
        template_dir,
        destination,
        {"package_name": "demo"},
        skip=skip,
        render_paths=True,
        ignore=["*.pyc"],
    )

    assert (destination / "demo.txt").read_text(encoding="utf-8") == "demo\n"
    assert not (destination / "skip-me.txt").exists()
    assert "skip-me.txt" in seen
    assert Path("demo.txt") in created


def test_render_templates_rejects_parent_path_escape(tmp_path: Path) -> None:
    template_dir = tmp_path / "template"
    destination = tmp_path / "out"
    template_dir.mkdir()
    destination.mkdir()
    (template_dir / "{{ name }}.txt.jinja").write_text("x\n", encoding="utf-8")

    with pytest.raises(SproutGenerationError, match="must stay within the destination directory"):
        render_templates(
            None,
            template_dir,
            destination,
            {"name": "../escape"},
            render_paths=True,
        )

    assert not (tmp_path / "escape.txt").exists()


def test_render_templates_rejects_absolute_rendered_path(tmp_path: Path) -> None:
    template_dir = tmp_path / "template"
    destination = tmp_path / "out"
    absolute_name = tmp_path / "escape"
    template_dir.mkdir()
    destination.mkdir()
    (template_dir / "{{ name }}.txt.jinja").write_text("x\n", encoding="utf-8")

    with pytest.raises(SproutGenerationError, match="must stay within the destination directory"):
        render_templates(
            None,
            template_dir,
            destination,
            {"name": str(absolute_name)},
            render_paths=True,
        )

    assert not absolute_name.with_suffix(".txt").exists()
