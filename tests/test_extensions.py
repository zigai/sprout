from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from jinja2 import Environment
from jinja2.ext import Extension

from sprout.extensions import CurrentYearExtension, GitDefaultsExtension, build_environment


class MarkerExtension(Extension):
    calls = 0

    def __init__(self, environment: Environment) -> None:
        super().__init__(environment)
        MarkerExtension.calls += 1
        environment.globals["marker"] = "ok"


def test_build_environment_applies_extensions_once(tmp_path: Path) -> None:
    MarkerExtension.calls = 0
    template_dir = tmp_path / "template"
    template_dir.mkdir()

    env = build_environment(template_dir, extensions=[MarkerExtension, MarkerExtension])

    assert env.globals["marker"] == "ok"
    assert MarkerExtension.calls == 1


def test_current_year_extension_sets_utc_year() -> None:
    env = Environment()
    CurrentYearExtension(env)

    assert env.globals["current_year"] == dt.datetime.now(tz=dt.UTC).year


def test_git_defaults_extension_sets_environment_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        GitDefaultsExtension,
        "_find_repo_config_path",
        lambda self, _start: None,
    )
    monkeypatch.setattr(
        GitDefaultsExtension,
        "_collect_git_config_paths",
        lambda self, _path: (),
    )
    monkeypatch.setattr(
        GitDefaultsExtension,
        "_get_git_config",
        lambda self, key: {
            "user.name": "Alice",
            "user.email": "alice@example.com",
        }.get(key, ""),
    )
    monkeypatch.setattr(
        GitDefaultsExtension,
        "_get_github_username",
        lambda self: "alice-gh",
    )

    env = Environment()
    GitDefaultsExtension(env)

    assert env.globals["git_user_name"] == "Alice"
    assert env.globals["git_user_email"] == "alice@example.com"
    assert env.globals["github_username"] == "alice-gh"


def test_collect_git_config_paths_includes_repo_home_and_xdg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    repo = tmp_path / "repo"
    home.mkdir()
    xdg.mkdir()
    repo.mkdir()

    home_gitconfig = home / ".gitconfig"
    xdg_git_config = xdg / "git" / "config"
    repo_config = repo / "config"
    home_gitconfig.write_text("[user]\nname = Home\n", encoding="utf-8")
    xdg_git_config.parent.mkdir(parents=True)
    xdg_git_config.write_text("[user]\nemail = xdg@example.com\n", encoding="utf-8")
    repo_config.write_text("[user]\nname = Repo\n", encoding="utf-8")

    monkeypatch.setattr("sprout.extensions.Path.home", lambda: home)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    extension = object.__new__(GitDefaultsExtension)
    paths = extension._collect_git_config_paths(repo_config)

    assert paths == (repo_config, home_gitconfig, xdg_git_config)


def test_find_repo_config_path_supports_dot_git_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    nested = project / "src" / "pkg"
    nested.mkdir(parents=True)
    config = project / ".git" / "config"
    config.parent.mkdir()
    config.write_text("[core]\nrepositoryformatversion = 0\n", encoding="utf-8")

    extension = object.__new__(GitDefaultsExtension)
    found = extension._find_repo_config_path(nested)

    assert found == config


def test_find_repo_config_path_supports_dot_git_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    nested = project / "src"
    nested.mkdir(parents=True)
    git_modules = tmp_path / "git-store" / "submodule"
    git_modules.mkdir(parents=True)
    config = git_modules / "config"
    config.write_text("[core]\nrepositoryformatversion = 0\n", encoding="utf-8")

    (project / ".git").write_text(f"gitdir: {git_modules}\n", encoding="utf-8")

    extension = object.__new__(GitDefaultsExtension)
    found = extension._find_repo_config_path(nested)

    assert found == config


def test_resolve_gitdir_and_load_config_edge_cases(tmp_path: Path) -> None:
    extension = object.__new__(GitDefaultsExtension)

    project = tmp_path / "project"
    project.mkdir()
    git_file = project / ".git"
    git_file.write_text("gitdir: .git/modules/main\n", encoding="utf-8")
    resolved = extension._resolve_gitdir(git_file)
    assert resolved == (project / ".git" / "modules" / "main").resolve()

    invalid_git_file = project / ".git-invalid"
    invalid_git_file.write_text("not-a-gitdir\n", encoding="utf-8")
    assert extension._resolve_gitdir(invalid_git_file) is None

    invalid_config = project / "invalid-config"
    invalid_config.write_bytes(b"\xff")
    assert extension._load_config(invalid_config) is None


def test_get_git_config_and_github_username(tmp_path: Path) -> None:
    config_a = tmp_path / "a.ini"
    config_b = tmp_path / "b.ini"
    config_a.write_text("[user]\nname = \n", encoding="utf-8")
    config_b.write_text("[user]\nname = Bob\nemail = bob@example.com\n", encoding="utf-8")

    extension = object.__new__(GitDefaultsExtension)
    extension._config_paths = (config_a, config_b)
    extension._repo_config_path = config_b

    assert extension._get_git_config("user.name") == "Bob"
    assert extension._get_git_config("invalid") == ""

    config_b.write_text(
        '[remote "origin"]\nurl = git@github.com:zigai/sprout.git\n',
        encoding="utf-8",
    )
    assert extension._get_github_username() == "zigai"


def test_get_github_username_falls_back_to_user_name(monkeypatch: pytest.MonkeyPatch) -> None:
    extension = object.__new__(GitDefaultsExtension)
    extension._repo_config_path = None
    monkeypatch.setattr(extension, "_get_git_config", lambda _key: "fallback-user")

    assert extension._get_github_username() == "fallback-user"
