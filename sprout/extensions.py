from __future__ import annotations

import configparser
import os
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from jinja2.ext import Extension


class GitDefaultsExtension(Extension):
    """Jinja extension that injects Git configuration defaults."""

    def __init__(self, environment: Environment) -> None:
        super().__init__(environment)
        self._repo_config_path = self._find_repo_config_path(Path.cwd())
        self._config_paths = self._collect_git_config_paths(self._repo_config_path)
        environment.globals["git_user_name"] = self._get_git_config("user.name")
        environment.globals["git_user_email"] = self._get_git_config("user.email")
        environment.globals["github_username"] = self._get_github_username()

    def _collect_git_config_paths(self, repo_config_path: Path | None) -> tuple[Path, ...]:
        config_paths: list[Path] = []
        if repo_config_path is not None:
            config_paths.append(repo_config_path)

        home = Path.home()
        xdg_config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        config_paths.extend(
            config_path
            for config_path in (home / ".gitconfig", xdg_config_home / "git" / "config")
            if config_path.is_file()
        )

        return tuple(config_paths)

    def _find_repo_config_path(self, start: Path) -> Path | None:
        for directory in (start, *start.parents):
            git_entry = directory / ".git"
            if git_entry.is_dir():
                config_path = git_entry / "config"
                if config_path.is_file():
                    return config_path
                continue

            if not git_entry.is_file():
                continue

            resolved_git_dir = self._resolve_gitdir(git_entry)
            if resolved_git_dir is None:
                continue

            config_path = resolved_git_dir / "config"
            if config_path.is_file():
                return config_path

        return None

    def _resolve_gitdir(self, git_file: Path) -> Path | None:
        try:
            raw_gitdir = git_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None

        if not raw_gitdir.startswith("gitdir:"):
            return None

        gitdir = raw_gitdir.partition(":")[2].strip()
        git_path = Path(gitdir)
        if git_path.is_absolute():
            return git_path
        return (git_file.parent / git_path).resolve()

    def _load_config(self, config_path: Path) -> configparser.ConfigParser | None:
        parser = configparser.ConfigParser(interpolation=None)
        try:
            loaded_paths = parser.read(config_path, encoding="utf-8")
        except (configparser.Error, OSError, UnicodeDecodeError):
            return None

        if not loaded_paths:
            return None
        return parser

    def _get_git_config(self, key: str) -> str:
        section, separator, option = key.partition(".")
        if not separator:
            return ""

        for config_path in self._config_paths:
            parser = self._load_config(config_path)
            if parser is None:
                continue
            value = parser.get(section, option, fallback="").strip()
            if value:
                return value
        return ""

    def _get_github_username(self) -> str:
        if self._repo_config_path is not None:
            parser = self._load_config(self._repo_config_path)
            if parser is not None:
                for section in parser.sections():
                    if not section.startswith('remote "'):
                        continue
                    remote_url = parser.get(section, "url", fallback="")
                    match = re.search(r"github\.com[:/]([^/]+)", remote_url)
                    if match:
                        return match.group(1)
        return self._get_git_config("user.name")


class CurrentYearExtension(Extension):
    def __init__(self, environment: Environment) -> None:
        super().__init__(environment)
        environment.globals["current_year"] = datetime.now(tz=datetime.UTC).year


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
        autoescape=select_autoescape(
            enabled_extensions=("html", "htm", "xml") if autoescape else (),
            default_for_string=autoescape,
            default=autoescape,
        ),
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


__all__ = ["CurrentYearExtension", "GitDefaultsExtension", "build_environment"]
