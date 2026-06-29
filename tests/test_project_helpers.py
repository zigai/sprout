from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sprout.project import (
    COMMON_LICENSE_CHOICES,
    github_install_source,
    github_repository_target,
    github_repository_url,
    is_github_repository_url,
    package_license_value,
    parse_github_repository_url,
    render_license_text,
    repository_git_url,
    run_git_post_actions,
    should_skip_license_file,
    validate_github_repository_url,
    validate_npm_package_name,
    validate_repository_name,
    validate_semver,
)


class FakeConsole:
    def __init__(self) -> None:
        self.messages: list[object] = []

    def print(self, message: object) -> None:
        self.messages.append(message)


def test_github_repository_helpers_parse_and_format_urls() -> None:
    repository = parse_github_repository_url("https://github.com/zigai/demo.git")

    assert repository is not None
    assert repository.owner == "zigai"
    assert repository.name == "demo"
    assert repository.target == "zigai/demo"
    assert repository.url == "https://github.com/zigai/demo"
    assert repository.git_url == "git+https://github.com/zigai/demo.git"
    assert repository.install_source == "github.com/zigai/demo"
    assert parse_github_repository_url("git@github.com:zigai/demo.git") == repository
    assert parse_github_repository_url("ssh://git@github.com/zigai/demo") == repository
    assert is_github_repository_url("https://github.com/zigai/demo") is True
    assert is_github_repository_url("https://example.com/zigai/demo") is False
    assert github_repository_url("zigai", "demo") == "https://github.com/zigai/demo"
    assert (
        repository_git_url("https://github.com/zigai/demo")
        == "git+https://github.com/zigai/demo.git"
    )
    assert github_install_source("https://github.com/zigai/demo") == "github.com/zigai/demo"


def test_github_repository_target_falls_back_to_repo_name() -> None:
    assert (
        github_repository_target(
            {
                "repository_url": "https://github.com/zigai/demo",
                "repo_name": "ignored",
            }
        )
        == "zigai/demo"
    )
    assert github_repository_target({"repo_name": "local-name"}) == "local-name"
    assert github_repository_target({}, fallback_repo_name="fallback") == "fallback"


@pytest.mark.parametrize(
    ("validator", "valid", "invalid"),
    [
        (validate_npm_package_name, "@scope/demo-package", "Demo Package"),
        (validate_repository_name, "demo.project_1", "demo/project"),
        (validate_semver, "1.2.3", "1.2"),
        (
            validate_github_repository_url,
            "https://github.com/zigai/demo",
            "https://example.com/demo",
        ),
    ],
)
def test_common_validators_accept_valid_values_and_reject_invalid_values(
    validator,
    valid: str,
    invalid: str,
) -> None:
    assert validator(valid) == (True, None)

    invalid_result, invalid_message = validator(invalid)

    assert invalid_result is False
    assert invalid_message


def test_license_helpers_cover_common_template_cases() -> None:
    assert COMMON_LICENSE_CHOICES[0] == ("None", "No license")
    assert package_license_value("None") == "UNLICENSED"
    assert package_license_value("MIT") == "MIT"
    assert should_skip_license_file("LICENSE.jinja", {"copyright_license": "None"}) is True
    assert should_skip_license_file("README.md.jinja", {"copyright_license": "None"}) is False

    mit_text = render_license_text("MIT", "Zig Author", year=2026)

    assert "MIT License" in mit_text
    assert "Copyright (c) 2026 Zig Author" in mit_text

    apache_text = render_license_text("Apache-2.0", "Zig Author", year=2026)

    assert "Apache License" in apache_text
    assert "Copyright 2026 Zig Author" in apache_text

    with pytest.raises(ValueError, match="not bundled"):
        render_license_text("GPL-3.0", "Zig Author", year=2026)


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

    monkeypatch.setattr("sprout.project.actions.shutil.which", fake_which)
    monkeypatch.setattr("sprout.project.actions.subprocess.run", fake_run)
    console = FakeConsole()

    result = run_git_post_actions(
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
    )

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
        "zigai/demo",
        "--private",
        "--description",
        "Demo project.",
        "--source",
        str(tmp_path),
        "--remote",
        "origin",
        "--push",
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

    monkeypatch.setattr("sprout.project.actions.shutil.which", lambda name: "/usr/bin/git")
    monkeypatch.setattr("sprout.project.actions.subprocess.run", fake_run)

    result = run_git_post_actions(tmp_path, {"git_init": True}, console=FakeConsole())

    assert result.initial_commit_ready is True
    assert result.github_repository_created is False
    assert ["/usr/bin/git", "commit", "-m", "chore: initialize project"] in commands
