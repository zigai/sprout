from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from jinja2.ext import Extension

from sprout.extensions.git_defaults import GitDefaultsExtension

DEFAULT_EXTENSIONS: tuple[type[Extension], ...] = (GitDefaultsExtension,)


def build_environment(
    template_dir: Path,
    *,
    extensions: Sequence[type[Extension]] | None = None,
    autoescape: bool = False,
    keep_trailing_newline: bool = True,
) -> Environment:
    """
    Build a Jinja environment configured for sprout templates.

    Args:
        template_dir (Path): Template root directory loaded by the file-system loader.
        extensions (Sequence[type[Extension]] | None): Optional extension classes to instantiate.
            If None, use `DEFAULT_EXTENSIONS`. Duplicate classes are ignored.
        autoescape (bool): Whether to enable Jinja autoescaping for HTML/XML-like templates.
        keep_trailing_newline (bool): Whether to preserve a final newline during rendering.
    """
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


__all__ = ["DEFAULT_EXTENSIONS", "build_environment"]
