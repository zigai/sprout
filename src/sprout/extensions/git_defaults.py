from __future__ import annotations

import shutil
import subprocess
from urllib.parse import urlsplit

from jinja2 import Environment
from jinja2.ext import Extension

from sprout.errors import SproutGenerationError


def get_default_branch() -> str:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise SproutGenerationError("Git is required to resolve the default branch.")

    try:
        result = subprocess.run(  # noqa: S603
            [git_executable, "var", "GIT_DEFAULT_BRANCH"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        raise SproutGenerationError("Could not resolve Git's default branch.") from e

    branch = result.stdout.strip()
    if result.returncode != 0 or not branch:
        raise SproutGenerationError("Could not resolve Git's default branch.")

    return branch


class GitDefaultsExtension(Extension):
    """Jinja extension that injects Git configuration defaults."""

    def __init__(self, environment: Environment) -> None:
        super().__init__(environment)

        # Jinja2 3.1.6 accepts arbitrary globals; Pyrefly 1.0.0 infers only builtins.
        # String globals are covered by test_main_renders_effective_git_default_branch;
        # remove the ignore when Jinja annotates Environment.globals accurately.
        environment.globals.update(default_branch=get_default_branch())  # pyrefly: ignore[bad-argument-type]
        environment.globals["git_user_name"] = self._get_git_config("user.name")  # pyrefly: ignore[unsupported-operation]
        environment.globals["git_user_email"] = self._get_git_config("user.email")  # pyrefly: ignore[unsupported-operation]
        environment.globals["github_username"] = self._get_github_username()  # pyrefly: ignore[unsupported-operation]

    def _get_git_config(self, key: str) -> str:
        return _query_git_config(key)

    def _get_github_username(self) -> str:
        for remote_url in _query_local_git_remotes():
            if remote_url.startswith("git@github.com:"):
                path = remote_url.removeprefix("git@github.com:")
            else:
                try:
                    parsed = urlsplit(remote_url)
                except ValueError:
                    continue

                if parsed.hostname != "github.com":
                    continue

                path = parsed.path.lstrip("/")

            owner = path.partition("/")[0]
            if owner:
                return owner

        return self._get_git_config("user.name")


def _query_git_config(key: str) -> str:
    git_executable = shutil.which("git")
    if git_executable is None:
        return ""

    try:
        result = subprocess.run(  # noqa: S603
            [git_executable, "config", "--get", key],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""

    if result.returncode == 0:
        return result.stdout.strip()

    return ""


def _query_local_git_remotes() -> list[str]:
    git_executable = shutil.which("git")
    if git_executable is None:
        return []

    try:
        result = subprocess.run(  # noqa: S603
            [git_executable, "config", "--local", "--get-regexp", r"^remote\..*\.url$"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []

    if result.returncode != 0:
        return []

    remotes: list[str] = []
    for line in result.stdout.splitlines():
        _, _, url = line.partition(" ")
        if url.strip():
            remotes.append(url.strip())

    return remotes


__all__ = ["GitDefaultsExtension", "get_default_branch"]
