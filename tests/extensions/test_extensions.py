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
    config_map: dict[str, str] = {
        "user.name": "Alice",
        "user.email": "alice@example.com",
    }
    monkeypatch.setattr(
        "sprout.extensions.git_defaults._query_git_config",
        lambda key: config_map.get(key, ""),
    )
    monkeypatch.setattr(
        "sprout.extensions.git_defaults._query_local_git_remotes",
        lambda: ["https://github.com/alice-gh/project.git"],
    )

    env = Environment()
    GitDefaultsExtension(env)

    assert env.globals["git_user_name"] == "Alice"
    assert env.globals["git_user_email"] == "alice@example.com"
    assert env.globals["github_username"] == "alice-gh"


def test_git_defaults_extension_handles_missing_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sprout.extensions.git_defaults.shutil.which", lambda name: None)

    env = Environment()
    GitDefaultsExtension(env)

    assert env.globals["git_user_name"] == ""
    assert env.globals["git_user_email"] == ""
    assert env.globals["github_username"] == ""


def test_get_github_username_from_ssh_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    config_map: dict[str, str] = {"user.name": "Bob"}
    monkeypatch.setattr(
        "sprout.extensions.git_defaults._query_git_config",
        lambda key: config_map.get(key, ""),
    )
    monkeypatch.setattr(
        "sprout.extensions.git_defaults._query_local_git_remotes",
        lambda: ["git@github.com:bob-org/repo.git"],
    )

    env = Environment()
    GitDefaultsExtension(env)

    assert env.globals["github_username"] == "bob-org"


def test_get_github_username_falls_back_to_user_name(monkeypatch: pytest.MonkeyPatch) -> None:
    config_map: dict[str, str] = {"user.name": "fallback-user"}
    monkeypatch.setattr(
        "sprout.extensions.git_defaults._query_git_config",
        lambda key: config_map.get(key, ""),
    )
    monkeypatch.setattr(
        "sprout.extensions.git_defaults._query_local_git_remotes",
        lambda: ["https://gitlab.com/group/repo.git"],
    )

    env = Environment()
    GitDefaultsExtension(env)

    assert env.globals["github_username"] == "fallback-user"
