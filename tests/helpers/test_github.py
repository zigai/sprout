from __future__ import annotations

from sprout.helpers import (
    github_install_source,
    github_repository_target,
    github_repository_url,
    is_github_repository_url,
    parse_github_repository_url,
    repository_git_url,
)


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


def test_repository_git_url_preserves_revision_fragment() -> None:
    assert (
        repository_git_url("https://github.com/team/repo#main")
        == "git+https://github.com/team/repo.git#main"
    )


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
