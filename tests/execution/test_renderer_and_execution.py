from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from jinja2 import Environment

from sprout.errors import (
    SproutGenerationError,
    SproutManifestError,
    SproutScaffoldError,
    SproutTemplateSourceError,
)
from sprout.execution import (
    ensure_destination,
    execute_manifest,
    invoke_apply,
    normalize_created_paths,
    resolve_template_directory,
)
from sprout.manifest import Manifest, ManifestContext
from sprout.prompt.style import Style
from sprout.renderer import render_templates
from sprout.scaffold import create_template_scaffold
from sprout.template_source import (
    TemplateSource,
    _normalise_git_url,
    _resolve_git_executable,
)


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


def test_render_templates_renders_and_copies(tmp_path: Path) -> None:
    template_dir = tmp_path / "template"
    destination = tmp_path / "out"
    template_dir.mkdir()
    destination.mkdir()
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


def test_invoke_apply_uses_manifest_context_and_normalises_result(tmp_path: Path) -> None:
    context = ManifestContext(
        env=Environment(),
        template_dir=tmp_path,
        template_root=tmp_path,
        destination=tmp_path,
        answers={"name": "demo"},
        style=Style(),
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
                style=Style(),
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
                style=Style(),
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


def test_template_source_owns_local_directory(tmp_path: Path) -> None:
    template = tmp_path / "template"
    template.mkdir()
    source = TemplateSource.from_source(str(template))

    assert source.root == template.resolve()
    source.close()


def test_create_template_scaffold_translates_filesystem_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "template"
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

    with pytest.raises(SproutScaffoldError) as raised:
        create_template_scaffold(root)

    assert str(raised.value) == f"failed to create template scaffold at {root}."
    assert raised.value.__cause__ is cause


def test_template_source_rejects_file(tmp_path: Path) -> None:
    file_path = tmp_path / "template.txt"
    file_path.write_text("x", encoding="utf-8")

    with pytest.raises(SproutTemplateSourceError, match="must be a directory"):
        TemplateSource.from_source(str(file_path))


def test_template_source_translates_temporary_directory_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cause = OSError("platform-specific detail")

    def fail_temporary_directory(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise cause

    monkeypatch.setattr("sprout.template_source._resolve_git_executable", lambda: "git")
    monkeypatch.setattr(
        "sprout.template_source.tempfile.TemporaryDirectory",
        fail_temporary_directory,
    )

    with pytest.raises(SproutTemplateSourceError) as raised:
        TemplateSource.from_source("owner/repo")

    assert str(raised.value) == "failed to create temporary directory for template clone."
    assert raised.value.__cause__ is cause


def test_template_source_translates_clone_launch_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cleanup_calls: list[str] = []
    cause = OSError("platform-specific detail")

    class FakeTemporaryDirectory:
        def __init__(self, prefix: str) -> None:
            self.name = str(tmp_path / prefix)

        def cleanup(self) -> None:
            cleanup_calls.append(self.name)

    def fail_run(args: list[str], **kwargs: object) -> object:
        del args, kwargs
        raise cause

    monkeypatch.setattr("sprout.template_source._resolve_git_executable", lambda: "git")
    monkeypatch.setattr(
        "sprout.template_source.tempfile.TemporaryDirectory", FakeTemporaryDirectory
    )
    monkeypatch.setattr("sprout.template_source.subprocess.run", fail_run)

    with pytest.raises(SproutTemplateSourceError) as raised:
        TemplateSource.from_source("owner/repo")

    assert str(raised.value) == "failed to launch git clone for remote template."
    assert raised.value.__cause__ is cause
    assert cleanup_calls == [str(tmp_path / "sprout-template-")]


def test_template_source_cleans_up_and_propagates_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cleanup_calls: list[str] = []
    interrupt = KeyboardInterrupt()

    class FakeTemporaryDirectory:
        def __init__(self, prefix: str) -> None:
            self.name = str(tmp_path / prefix)

        def cleanup(self) -> None:
            cleanup_calls.append(self.name)

    def interrupt_clone(args: list[str], **kwargs: object) -> object:
        del args, kwargs
        raise interrupt

    monkeypatch.setattr("sprout.template_source._resolve_git_executable", lambda: "git")
    monkeypatch.setattr(
        "sprout.template_source.tempfile.TemporaryDirectory", FakeTemporaryDirectory
    )
    monkeypatch.setattr("sprout.template_source.subprocess.run", interrupt_clone)

    with pytest.raises(KeyboardInterrupt) as raised:
        TemplateSource.from_source("owner/repo")

    assert raised.value is interrupt
    assert cleanup_calls == [str(tmp_path / "sprout-template-")]


def test_template_source_remote_clone_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("sprout.template_source._resolve_git_executable", lambda: "git")
    cleanup_calls: list[str] = []
    cause = subprocess.CalledProcessError(
        1,
        ["git", "clone"],
        stderr="fatal: not found",
    )

    class FakeTemporaryDirectory:
        def __init__(self, prefix: str) -> None:
            self.name = str(tmp_path / prefix)

        def cleanup(self) -> None:
            cleanup_calls.append(self.name)

    monkeypatch.setattr(
        "sprout.template_source.tempfile.TemporaryDirectory", FakeTemporaryDirectory
    )

    def fake_run(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise cause

    monkeypatch.setattr("sprout.template_source.subprocess.run", fake_run)

    with pytest.raises(SproutTemplateSourceError) as raised:
        TemplateSource.from_source("owner/repo")

    assert str(raised.value) == "failed to clone remote template."
    assert raised.value.__cause__ is cause
    assert cleanup_calls == [str(tmp_path / "sprout-template-")]


def test_template_source_remote_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    created_temp = tmp_path / "download"
    created_temp.mkdir()
    cleanup_calls: list[str] = []

    class FakeTemporaryDirectory:
        def __init__(self, prefix: str) -> None:
            self.name = str(created_temp)

        def cleanup(self) -> None:
            cleanup_calls.append(self.name)

    monkeypatch.setattr("sprout.template_source._resolve_git_executable", lambda: "git")
    monkeypatch.setattr(
        "sprout.template_source.tempfile.TemporaryDirectory", FakeTemporaryDirectory
    )

    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("sprout.template_source.subprocess.run", fake_run)

    source = TemplateSource.from_source("owner/repo")

    assert source.root == created_temp / "template"
    assert calls
    assert calls[0][:3] == ["git", "clone", "--depth"]
    source.close()
    source.close()
    assert cleanup_calls == [str(created_temp)]


def test_resolve_git_executable_and_url_normalisation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sprout.template_source.shutil.which", lambda _name: None)

    with pytest.raises(SproutTemplateSourceError, match="git is required"):
        _resolve_git_executable()

    assert _normalise_git_url("owner/repo") == "https://github.com/owner/repo.git"
    assert _normalise_git_url("https://example.com/repo.git") == "https://example.com/repo.git"
    assert _normalise_git_url("owner/repo.git") == "https://github.com/owner/repo.git"
    assert _normalise_git_url("local/path with space") == "local/path with space"
