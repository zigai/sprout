from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from jinja2.ext import Extension


class GitDefaultsExtension(Extension):
    """Jinja extension that injects Git configuration defaults."""

    def __init__(self, environment: Environment) -> None:
        super().__init__(environment)
        environment.globals["git_user_name"] = self._get_git_config("user.name")
        environment.globals["git_user_email"] = self._get_git_config("user.email")
        environment.globals["github_username"] = self._get_github_username()

    def _get_git_config(self, key: str) -> str:
        try:
            result = subprocess.run(
                ["git", "config", "--get", key],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""

    def _get_github_username(self) -> str:
        try:
            result = subprocess.run(
                ["git", "remote", "-v"],
                capture_output=True,
                text=True,
                check=True,
            )
            for line in result.stdout.splitlines():
                if "github.com" in line:
                    match = re.search(r"github\.com[:/]([^/]+)", line)
                    if match:
                        return match.group(1)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""
        return ""


class CurrentYearExtension(Extension):
    def __init__(self, environment: Environment):
        super().__init__(environment)
        environment.globals["current_year"] = date.today().year


DEFAULT_EXTENSIONS: tuple[type[Extension], ...] = (GitDefaultsExtension,)


def build_environment(
    template_dir: Path,
    *,
    extensions: Sequence[type[Extension]] | None = None,
    autoescape: bool = False,
    keep_trailing_newline: bool = True,
) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=autoescape,
        keep_trailing_newline=keep_trailing_newline,
    )

    extensions = extensions or DEFAULT_EXTENSIONS
    applied: set[type[Extension]] = set()

    for extension_cls in extensions or ():
        if extension_cls in applied:
            continue
        extension_cls(env)
        applied.add(extension_cls)

    return env


__all__ = ["GitDefaultsExtension", "CurrentYearExtension", "build_environment"]
