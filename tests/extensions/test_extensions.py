from __future__ import annotations

import datetime as dt
import os
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


@pytest.mark.parametrize(
    ("config_map", "remotes", "expected_username"),
    [
        pytest.param(
            {"user.name": "Bob"},
            ["git@github.com:bob-org/repo.git"],
            "bob-org",
            id="ssh-remote",
        ),
        pytest.param(
            {"user.name": "fallback-user"},
            ["https://gitlab.com/group/repo.git"],
            "fallback-user",
            id="non-github-remote",
        ),
    ],
)
def test_git_defaults_resolves_github_username(
    monkeypatch: pytest.MonkeyPatch,
    config_map: dict[str, str],
    remotes: list[str],
    expected_username: str,
) -> None:
    monkeypatch.setattr(
        "sprout.extensions.git_defaults._query_git_config",
        lambda key: config_map.get(key, ""),
    )
    monkeypatch.setattr(
        "sprout.extensions.git_defaults._query_local_git_remotes",
        lambda: remotes,
    )

    env = Environment()
    GitDefaultsExtension(env)

    assert env.globals["github_username"] == expected_username


def test_git_defaults_ignores_github_lookalike_host_in_local_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    git_dir = tmp_path / ".git"
    (git_dir / "objects").mkdir(parents=True)
    (git_dir / "refs").mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "config").write_text(
        "[core]\nrepositoryformatversion = 0\n"
        "[user]\nname = fallback-user\n"
        '[remote "origin"]\nurl = https://notgithub.com/foreign/repo\n',
        encoding="utf-8",
    )
    global_config = tmp_path / "global-config"
    global_config.write_text("", encoding="utf-8")
    for name in os.environ:
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.chdir(tmp_path)

    env = Environment()
    GitDefaultsExtension(env)

    assert env.globals["github_username"] == "fallback-user"
