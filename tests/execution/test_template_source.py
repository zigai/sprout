from __future__ import annotations

import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest

from sprout.errors import SproutTemplateSourceError
from sprout.template_source import TemplateSource, _parse_remote_source, _resolve_git_executable


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


def test_resolve_git_executable_reports_missing_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sprout.template_source.shutil.which", lambda _name: None)

    with pytest.raises(SproutTemplateSourceError, match="git is required"):
        _resolve_git_executable()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("owner/repo", ("https://github.com/owner/repo.git", None)),
        ("owner/repo.git", ("https://github.com/owner/repo.git", None)),
        (
            "owner/repo/templates/game/",
            ("https://github.com/owner/repo.git", PurePosixPath("templates/game")),
        ),
        ("https://example.com/repo.git", ("https://example.com/repo.git", None)),
        (
            "https://example.com/repo.git#templates/game",
            ("https://example.com/repo.git", PurePosixPath("templates/game")),
        ),
        (
            "git@github.com:owner/repo.git#templates/game",
            ("git@github.com:owner/repo.git", PurePosixPath("templates/game")),
        ),
        (
            "file:///srv/repo.git#./templates//game",
            ("file:///srv/repo.git", PurePosixPath("templates/game")),
        ),
        ("local/path with space", ("local/path with space", None)),
    ],
)
def test_parse_remote_source(source: str, expected: tuple[str, PurePosixPath | None]) -> None:
    assert _parse_remote_source(source) == expected


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("https://example.com/repo.git#", "empty template path"),
        ("https://example.com/repo.git#/", "empty template path"),
        ("https://example.com/repo.git#templates/../../x", "escapes the repository"),
        ("owner/repo/../x", "escapes the repository"),
    ],
)
def test_parse_remote_source_rejects_invalid_template_path(source: str, message: str) -> None:
    with pytest.raises(SproutTemplateSourceError, match=message):
        _parse_remote_source(source)


def _git(*args: str) -> None:
    git_executable = shutil.which("git")
    assert git_executable is not None
    subprocess.run(
        [
            git_executable,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            *args,
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def template_repo(tmp_path: Path) -> str:
    repo = tmp_path / "repo"
    files = {
        "templates/demo/sprout.py": "questions = []\n",
        "templates/demo/template/README.md": "demo\n",
        "templates/empty/README.md": "no manifest\n",
        "unrelated/data.txt": "unrelated\n",
    }
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (repo / "templates" / "outside").symlink_to(tmp_path, target_is_directory=True)
    _git("init", "--quiet", str(repo))
    _git("-C", str(repo), "add", "--all")
    _git("-C", str(repo), "commit", "--quiet", "--no-verify", "--message", "chore: init")

    return repo.as_uri()


@pytest.fixture
def clone_tempdir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    tempdir = tmp_path / "clones"
    tempdir.mkdir()
    monkeypatch.setattr("sprout.template_source.tempfile.tempdir", str(tempdir))

    return tempdir


def test_template_source_clones_only_repository_subdirectory(
    template_repo: str,
    clone_tempdir: Path,
) -> None:
    source = TemplateSource.from_source(f"{template_repo}#templates/demo")
    clone_dir = source.root.parent.parent

    assert source.root.name == "demo"
    assert (source.root / "sprout.py").is_file()
    assert (source.root / "template" / "README.md").is_file()
    assert not (clone_dir / "unrelated").exists()

    source.close()

    assert list(clone_tempdir.iterdir()) == []


@pytest.mark.parametrize(
    ("template_path", "message"),
    [
        ("templates/missing", "is not a directory in the repository"),
        ("templates/demo/sprout.py", "is not a directory in the repository"),
        ("templates/empty", "has no sprout.py"),
        ("templates/outside", "resolves outside the repository"),
    ],
)
def test_template_source_rejects_invalid_repository_subdirectory(
    template_repo: str,
    clone_tempdir: Path,
    template_path: str,
    message: str,
) -> None:
    with pytest.raises(SproutTemplateSourceError, match=message):
        TemplateSource.from_source(f"{template_repo}#{template_path}")

    assert list(clone_tempdir.iterdir()) == []


def test_template_source_cleans_up_when_sparse_checkout_fails(
    monkeypatch: pytest.MonkeyPatch,
    clone_tempdir: Path,
) -> None:
    def fail_sparse_checkout(args: list[str], **kwargs: object) -> object:
        del kwargs
        if "sparse-checkout" in args:
            raise subprocess.CalledProcessError(128, args, stderr="fatal: sparse")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("sprout.template_source.subprocess.run", fail_sparse_checkout)

    with pytest.raises(SproutTemplateSourceError, match="failed to clone remote template"):
        TemplateSource.from_source("owner/repo/templates/demo")

    assert list(clone_tempdir.iterdir()) == []
