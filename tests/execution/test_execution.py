from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment

from sprout.errors import SproutGenerationError, SproutManifestError
from sprout.execution import (
    ensure_destination,
    execute_manifest,
    invoke_apply,
    normalize_created_paths,
    resolve_template_directory,
)
from sprout.manifest import Manifest, ManifestContext
from sprout.prompt.style import CompactStyle


def test_ensure_destination_creates_directory(tmp_path: Path) -> None:
    destination = tmp_path / "new-project"

    ensure_destination(destination, force=False)

    assert destination.exists()
    assert destination.is_dir()


def test_ensure_destination_translates_filesystem_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "new-project"
    cause = OSError("platform-specific detail")

    def fail_mkdir(self: Path, parents: bool = False, exist_ok: bool = False) -> None:
        del self, parents, exist_ok
        raise cause

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    with pytest.raises(SproutGenerationError) as raised:
        ensure_destination(destination, force=False)

    assert str(raised.value) == f"failed to prepare destination '{destination}'."
    assert raised.value.__cause__ is cause


def test_ensure_destination_rejects_file(tmp_path: Path) -> None:
    destination = tmp_path / "file.txt"
    destination.write_text("x", encoding="utf-8")

    with pytest.raises(SproutGenerationError, match="is a file"):
        ensure_destination(destination, force=False)


def test_ensure_destination_non_empty_requires_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "project"
    destination.mkdir()
    (destination / "README.md").write_text("content", encoding="utf-8")

    monkeypatch.setattr("sprout.execution.confirm_overwrite", lambda _path, style: False)

    with pytest.raises(SproutGenerationError, match="aborted by user"):
        ensure_destination(destination, force=False)


def test_invoke_apply_uses_manifest_context_and_normalises_result(tmp_path: Path) -> None:
    context = ManifestContext(
        env=Environment(),
        template_dir=tmp_path,
        template_root=tmp_path,
        destination=tmp_path,
        answers={"name": "demo"},
        style=CompactStyle(),
    )

    def apply_fn(context: ManifestContext) -> Path:
        assert context.answers["name"] == "demo"

        return context.destination / "README.md"

    result = invoke_apply(apply_fn, context=context)

    assert result == [tmp_path / "README.md"]


def test_invoke_apply_rejects_invalid_return_type(tmp_path: Path) -> None:
    with pytest.raises(SproutManifestError, match="must return None, a path, or a sequence"):
        invoke_apply(
            lambda context: 5,
            context=ManifestContext(
                env=Environment(),
                template_dir=tmp_path,
                template_root=tmp_path,
                destination=tmp_path,
                answers={},
                style=CompactStyle(),
            ),
        )


def test_invoke_apply_rejects_unsupported_required_parameter(tmp_path: Path) -> None:
    def apply_fn(required: str) -> None:
        raise AssertionError(f"unexpected argument: {required}")

    with pytest.raises(SproutManifestError, match="must accept exactly one parameter: context"):
        invoke_apply(
            apply_fn,
            context=ManifestContext(
                env=Environment(),
                template_dir=tmp_path,
                template_root=tmp_path,
                destination=tmp_path,
                answers={},
                style=CompactStyle(),
            ),
        )


def test_execute_manifest_with_apply_returning_none(tmp_path: Path) -> None:
    template_root = tmp_path / "template-source"
    template_root.mkdir()

    manifest = Manifest(
        questions=[],
        apply=lambda context: None,
        template_dir="template",
    )
    destination = tmp_path / "dest"

    answers, created = execute_manifest(
        manifest,
        template_dir=template_root,
        destination=destination,
        initial_answers={},
    )

    assert answers == {}
    assert created is None


def test_execute_manifest_with_apply_returning_single_path(tmp_path: Path) -> None:
    template_root = tmp_path / "template-source"
    template_root.mkdir()
    destination = tmp_path / "dest"

    def apply(context: ManifestContext) -> Path:
        file_path = context.destination / "output.txt"
        file_path.write_text("hello", encoding="utf-8")
        return file_path

    manifest = Manifest(
        questions=[],
        apply=apply,
        template_dir="template",
    )

    answers, created = execute_manifest(
        manifest,
        template_dir=template_root,
        destination=destination,
        initial_answers={},
    )

    assert answers == {}
    assert created == [Path("output.txt")]


def test_execute_manifest_errors_when_template_dir_missing(tmp_path: Path) -> None:
    template_root = tmp_path / "template-source"
    template_root.mkdir()
    destination = tmp_path / "dest"

    with pytest.raises(SproutGenerationError, match="Template directory not found"):
        execute_manifest(
            Manifest(questions=[], template_dir="missing"),
            template_dir=template_root,
            destination=destination,
            initial_answers={},
        )


def test_normalize_created_paths_and_template_dir_resolution(tmp_path: Path) -> None:
    destination = tmp_path / "project"
    destination.mkdir()
    absolute = destination / "README.md"
    absolute.write_text("x", encoding="utf-8")

    created = normalize_created_paths([absolute, "docs/info.md"], destination)
    assert created == [Path("README.md"), Path("docs/info.md")]

    root = tmp_path / "source"
    root.mkdir()
    assert resolve_template_directory(root, None) == (root / "template").resolve()
    assert resolve_template_directory(root, "tpl") == (root / "tpl").resolve()
