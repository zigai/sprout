from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sprout.errors import SproutTemplateSourceError
from sprout.template_source import TemplateSource, _normalise_git_url, _resolve_git_executable


@pytest.fixture
def cleanup_calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    calls: list[str] = []

    class FakeTemporaryDirectory:
        def __init__(self, prefix: str) -> None:
            self.name = str(tmp_path / prefix)

        def cleanup(self) -> None:
            calls.append(self.name)

    monkeypatch.setattr(
        "sprout.template_source.tempfile.TemporaryDirectory", FakeTemporaryDirectory
    )
    return calls


def test_template_source_owns_local_directory(tmp_path: Path) -> None:
    template = tmp_path / "template"
    template.mkdir()
    source = TemplateSource.from_source(str(template))

    assert source.root == template.resolve()
    source.close()


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
    cleanup_calls: list[str],
) -> None:
    cause = OSError("platform-specific detail")

    def fail_run(args: list[str], **kwargs: object) -> object:
        del args, kwargs
        raise cause

    monkeypatch.setattr("sprout.template_source._resolve_git_executable", lambda: "git")
    monkeypatch.setattr("sprout.template_source.subprocess.run", fail_run)

    with pytest.raises(SproutTemplateSourceError) as raised:
        TemplateSource.from_source("owner/repo")

    assert str(raised.value) == "failed to launch git clone for remote template."
    assert raised.value.__cause__ is cause
    assert cleanup_calls == [str(tmp_path / "sprout-template-")]


def test_template_source_cleans_up_and_propagates_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cleanup_calls: list[str],
) -> None:
    interrupt = KeyboardInterrupt()

    def interrupt_clone(args: list[str], **kwargs: object) -> object:
        del args, kwargs
        raise interrupt

    monkeypatch.setattr("sprout.template_source._resolve_git_executable", lambda: "git")
    monkeypatch.setattr("sprout.template_source.subprocess.run", interrupt_clone)

    with pytest.raises(KeyboardInterrupt) as raised:
        TemplateSource.from_source("owner/repo")

    assert raised.value is interrupt
    assert cleanup_calls == [str(tmp_path / "sprout-template-")]


def test_template_source_remote_clone_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cleanup_calls: list[str],
) -> None:
    monkeypatch.setattr("sprout.template_source._resolve_git_executable", lambda: "git")
    cause = subprocess.CalledProcessError(
        1,
        ["git", "clone"],
        stderr="fatal: not found",
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
