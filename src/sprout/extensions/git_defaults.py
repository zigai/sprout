from __future__ import annotations

import re
import shutil
import subprocess

from jinja2 import Environment
from jinja2.ext import Extension


class GitDefaultsExtension(Extension):
    """Jinja extension that injects Git configuration defaults."""

    def __init__(self, environment: Environment) -> None:
        super().__init__(environment)

        environment.globals["git_user_name"] = self._get_git_config("user.name")  # pyrefly: ignore[unsupported-operation]
        environment.globals["git_user_email"] = self._get_git_config("user.email")  # pyrefly: ignore[unsupported-operation]
        environment.globals["github_username"] = self._get_github_username()  # pyrefly: ignore[unsupported-operation]

    def _get_git_config(self, key: str) -> str:
        return _query_git_config(key)

    def _get_github_username(self) -> str:
        for remote_url in _query_local_git_remotes():
            match = re.search(r"github\.com[:/]([^/]+)", remote_url)
            if match:
                return match.group(1)

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


__all__ = ["GitDefaultsExtension"]
