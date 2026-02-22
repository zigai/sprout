from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from jinja2 import Environment

from sprout.cli import (
    Manifest,
    _invoke_apply,
    _normalise_created,
    _normalise_git_url,
    _prepare_template_source,
    _resolve_actual_template_dir,
    _resolve_git_executable,
    ensure_destination,
    execute_manifest,
    render_templates,
)
from sprout.style import Style


def test_ensure_destination_creates_directory(tmp_path: Path) -> None:
    destination = tmp_path / "new-project"

    ensure_destination(destination, force=False)

    assert destination.exists()
    assert destination.is_dir()


def test_ensure_destination_rejects_file(tmp_path: Path) -> None:
    destination = tmp_path / "file.txt"
    destination.write_text("x", encoding="utf-8")

    with pytest.raises(SystemExit, match="is a file"):
        ensure_destination(destination, force=False)


def test_ensure_destination_non_empty_requires_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "project"
    destination.mkdir()
    (destination / "README.md").write_text("content", encoding="utf-8")

    monkeypatch.setattr("sprout.cli._confirm_overwrite", lambda _path, style: False)

    with pytest.raises(SystemExit, match="aborted by user"):
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


def test_invoke_apply_injects_arguments_and_normalises_result(tmp_path: Path) -> None:
    environment = Environment()
    template_dir = tmp_path / "template"
    template_dir.mkdir()
    destination = tmp_path / "dest"
    destination.mkdir()
    answers = {"name": "demo"}
    style = Style()

    def apply_fn(env: Environment, destination: Path, answers: dict[str, object]) -> str:
        assert env is environment
        assert destination.exists()
        assert answers["name"] == "demo"
        return "README.md"

    result = _invoke_apply(
        apply_fn,
        env=environment,
        template_dir=template_dir,
        template_root=tmp_path,
        destination=destination,
        answers=answers,
        style=style,
    )

    assert result == ["README.md"]


def test_invoke_apply_rejects_invalid_return_type(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="must return None, a path, or a sequence"):
        _invoke_apply(
            lambda: 5,
            env=Environment(),
            template_dir=tmp_path,
            template_root=tmp_path,
            destination=tmp_path,
            answers={},
            style=Style(),
        )


def test_invoke_apply_wraps_type_error(tmp_path: Path) -> None:
    def apply_fn(required: str) -> None:
        raise AssertionError(f"unexpected argument: {required}")

    with pytest.raises(SystemExit, match="failed to run apply"):
        _invoke_apply(
            apply_fn,
            env=Environment(),
            template_dir=tmp_path,
            template_root=tmp_path,
            destination=tmp_path,
            answers={},
            style=Style(),
        )


def test_execute_manifest_with_apply_returning_none(tmp_path: Path) -> None:
    template_root = tmp_path / "template-source"
    template_root.mkdir()

    manifest = Manifest(
        questions=[],
        apply=lambda **_kwargs: None,
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


def test_execute_manifest_errors_when_template_dir_missing(tmp_path: Path) -> None:
    template_root = tmp_path / "template-source"
    template_root.mkdir()
    destination = tmp_path / "dest"

    with pytest.raises(SystemExit, match="Template directory not found"):
        execute_manifest(
            Manifest(questions=[], template_dir="missing"),
            template_dir=template_root,
            destination=destination,
            initial_answers={},
        )


def test_normalise_created_and_template_dir_resolution(tmp_path: Path) -> None:
    destination = tmp_path / "project"
    destination.mkdir()
    absolute = destination / "README.md"
    absolute.write_text("x", encoding="utf-8")

    created = _normalise_created([absolute, "docs/info.md"], destination)
    assert created == [Path("README.md"), Path("docs/info.md")]

    root = tmp_path / "source"
    root.mkdir()
    assert _resolve_actual_template_dir(root, None) == (root / "template").resolve()
    assert _resolve_actual_template_dir(root, "tpl") == (root / "tpl").resolve()


def test_prepare_template_source_for_local_directory(tmp_path: Path) -> None:
    template = tmp_path / "template"
    template.mkdir()
    resolved, cleanup = _prepare_template_source(str(template))

    assert resolved == template.resolve()
    cleanup()


def test_prepare_template_source_rejects_file(tmp_path: Path) -> None:
    file_path = tmp_path / "template.txt"
    file_path.write_text("x", encoding="utf-8")

    with pytest.raises(SystemExit, match="must be a directory"):
        _prepare_template_source(str(file_path))


def test_prepare_template_source_remote_clone_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sprout.cli._resolve_git_executable", lambda: "git")

    def fake_run(*_args: object, **_kwargs: object) -> object:
        raise subprocess.CalledProcessError(
            1,
            ["git", "clone"],
            stderr="fatal: not found",
        )

    monkeypatch.setattr("sprout.cli.subprocess.run", fake_run)

    with pytest.raises(SystemExit, match="failed to clone template"):
        _prepare_template_source("owner/repo")


def test_prepare_template_source_remote_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created_temp = tmp_path / "download"
    created_temp.mkdir()
    monkeypatch.setattr("sprout.cli._resolve_git_executable", lambda: "git")
    monkeypatch.setattr("sprout.cli.tempfile.mkdtemp", lambda prefix: str(created_temp))

    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("sprout.cli.subprocess.run", fake_run)

    resolved, cleanup = _prepare_template_source("owner/repo")

    assert resolved == created_temp / "template"
    assert calls
    assert calls[0][:3] == ["git", "clone", "--depth"]
    cleanup()


def test_resolve_git_executable_and_url_normalisation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sprout.cli.shutil.which", lambda _name: None)
    with pytest.raises(SystemExit, match="git is required"):
        _resolve_git_executable()

    assert _normalise_git_url("owner/repo") == "https://github.com/owner/repo.git"
    assert _normalise_git_url("https://example.com/repo.git") == "https://example.com/repo.git"
    assert _normalise_git_url("owner/repo.git") == "https://github.com/owner/repo.git"
    assert _normalise_git_url("local/path with space") == "local/path with space"
