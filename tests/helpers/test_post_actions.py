from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sprout.helpers import ProjectPostActions, run_git_post_actions


class FakeConsole:
    def __init__(self) -> None:
        self.messages: list[object] = []

    def print(self, message: object) -> None:
        self.messages.append(message)


def test_run_git_post_actions_creates_initial_commit_and_github_repo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    commands: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        if name in {"gh", "git"}:
            return f"/usr/bin/{name}"

        return None

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == tmp_path
        assert check is False
        commands.append(command)
        returncode = 1 if command[:4] == ["/usr/bin/git", "diff", "--cached", "--quiet"] else 0

        return subprocess.CompletedProcess(command, returncode, "", "")

    monkeypatch.setattr("sprout.helpers.post_actions.shutil.which", fake_which)
    monkeypatch.setattr("sprout.helpers.post_actions.subprocess.run", fake_run)
    console = FakeConsole()

    result = ProjectPostActions(
        tmp_path,
        {
            "author_name": "Zig Author",
            "author_email": "zig@example.com",
            "create_github_repo": True,
            "description": "Demo project.",
            "github_repo_visibility": "private",
            "repository_url": "https://github.com/zigai/demo",
            "repo_name": "ignored",
        },
        console=console,
    ).run()

    assert result.initial_commit_ready is True
    assert result.github_repository_created is True
    assert ["/usr/bin/git", "add", "--all"] in commands
    assert [
        "/usr/bin/git",
        "-c",
        "user.name=Zig Author",
        "-c",
        "user.email=zig@example.com",
        "commit",
        "-m",
        "chore: initialize project",
    ] in commands
    assert [
        "/usr/bin/gh",
        "repo",
        "create",
        "--private",
        "--description",
        "Demo project.",
        "--source",
        str(tmp_path),
        "--remote",
        "origin",
        "--",
        "zigai/demo",
    ] in commands
    assert [
        "/usr/bin/git",
        "-c",
        "credential.helper=",
        "-c",
        "credential.helper=!/usr/bin/gh auth git-credential",
        "push",
        "--set-upstream",
        "origin",
        "HEAD",
    ] in commands
    assert not any(command[:2] == ["/usr/bin/gh", "api"] for command in commands)
    assert not any(command[:3] == ["/usr/bin/git", "branch", "-M"] for command in commands)
    assert console.messages == []


def test_create_github_repo_passes_option_like_name_as_argument(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(command)

        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "sprout.helpers.post_actions.shutil.which",
        lambda name: "/usr/bin/gh" if name == "gh" else None,
    )
    monkeypatch.setattr("sprout.helpers.post_actions.subprocess.run", fake_run)

    ProjectPostActions(
        tmp_path,
        {"repo_name": "--help"},
        console=FakeConsole(),
    ).create_github_repo()

    assert commands[0][-2:] == ["--", "--help"]


def test_run_git_post_actions_uses_github_default_branch_for_new_repo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        if name in {"gh", "git"}:
            return f"/usr/bin/{name}"

        return None

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == tmp_path
        assert check is False
        commands.append(command)

        if command[:3] == ["/usr/bin/git", "init", "-b"]:
            (tmp_path / ".git").mkdir()

        if command[:4] == ["/usr/bin/git", "diff", "--cached", "--quiet"]:
            return subprocess.CompletedProcess(command, 1, "", "")
        if command[:3] == ["/usr/bin/gh", "api", "repos/{owner}/{repo}"]:
            return subprocess.CompletedProcess(command, 0, "trunk\n", "")

        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("sprout.helpers.post_actions.shutil.which", fake_which)
    monkeypatch.setattr("sprout.helpers.post_actions.subprocess.run", fake_run)
    console = FakeConsole()

    result = ProjectPostActions(
        tmp_path,
        {
            "create_github_repo": True,
            "github_repo_visibility": "public",
            "repo_name": "demo",
            "repository_url": "https://github.com/zigai/demo",
        },
        console=console,
    ).run()

    assert result.initial_commit_ready is True
    assert result.github_repository_created is True
    assert ["/usr/bin/git", "branch", "-M", "trunk"] in commands
    assert [
        "/usr/bin/git",
        "-c",
        "credential.helper=",
        "-c",
        "credential.helper=!/usr/bin/gh auth git-credential",
        "push",
        "--set-upstream",
        "origin",
        "trunk",
    ] in commands
    assert console.messages == []


def test_run_git_post_actions_initializes_git_without_github(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == tmp_path
        assert check is False
        commands.append(command)
        returncode = 1 if command[:4] == ["/usr/bin/git", "diff", "--cached", "--quiet"] else 0

        return subprocess.CompletedProcess(command, returncode, "", "")

    monkeypatch.setattr("sprout.helpers.post_actions.shutil.which", lambda name: "/usr/bin/git")
    monkeypatch.setattr("sprout.helpers.post_actions.subprocess.run", fake_run)

    result = run_git_post_actions(tmp_path, {"git_init": True}, console=FakeConsole())

    assert result.initial_commit_ready is True
    assert result.github_repository_created is False
    assert ["/usr/bin/git", "commit", "-m", "chore: initialize project"] in commands
