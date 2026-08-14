from __future__ import annotations

import fnmatch
import shutil
from collections.abc import Sequence
from pathlib import Path

from jinja2 import Environment
from jinja2.ext import Extension

from sprout.errors import SproutGenerationError
from sprout.extensions.environment import build_environment
from sprout.manifest import SkipPredicate
from sprout.prompt.question import DefaultValue


def _merge_ignore_patterns(ignore: Sequence[str] | None) -> list[str]:
    patterns = list(ignore or ())
    for pattern in ("*.pyc", "*.pyo", "*.pyd", "*.swp", "*~", ".DS_Store"):
        if pattern not in patterns:
            patterns.append(pattern)

    return patterns


def _should_ignore_path(path: Path, ignore_patterns: Sequence[str]) -> bool:
    if "__pycache__" in path.parts:
        return True

    return any(fnmatch.fnmatch(path.name, pattern) for pattern in ignore_patterns)


class TemplateRenderer:
    """Render files from one template directory into one destination."""

    def __init__(
        self,
        *,
        env: Environment,
        template_dir: Path,
        destination: Path,
        answers: dict[str, DefaultValue],
        skip: SkipPredicate | None = None,
        render_paths: bool = False,
        ignore: Sequence[str] | None = None,
    ) -> None:
        self.env = env
        self.template_dir = template_dir
        self.destination = destination
        self.answers = answers
        self.skip = skip
        self.render_paths = render_paths
        self.ignore_patterns = _merge_ignore_patterns(ignore)

    def render(self) -> list[Path]:
        created: list[Path] = []

        for source in sorted(self.template_dir.rglob("*")):
            if source.is_dir() or _should_ignore_path(source, self.ignore_patterns):
                continue

            relative = source.relative_to(self.template_dir)
            relative_str = relative.as_posix()
            if self.skip and self.skip(relative_str, self.answers):
                continue

            target_relative = self._resolve_target_relative(source, relative)
            self._render_source_file(source, target_relative, relative_str)
            created.append(target_relative)

        return created

    def _resolve_target_relative(self, source: Path, relative: Path) -> Path:
        if self.render_paths:
            rendered = self.env.from_string(relative.as_posix()).render(**self.answers)
            target_relative = Path(rendered)
        else:
            target_relative = relative

        if source.suffix == ".jinja":
            target_relative = target_relative.with_suffix("")

        if target_relative == Path():
            raise SproutGenerationError(
                f"rendered path for '{relative.as_posix()}' must not be empty."
            )

        if target_relative.is_absolute() or ".." in target_relative.parts:
            raise SproutGenerationError(
                f"rendered path for '{relative.as_posix()}' must stay within the destination directory."
            )

        return target_relative

    def _render_source_file(self, source: Path, target_relative: Path, relative_str: str) -> None:
        target_path = self.destination / target_relative
        if source.suffix == ".jinja":
            template = self.env.get_template(relative_str)
            rendered = template.render(**self.answers)
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(rendered, encoding="utf-8")
            except OSError as e:
                raise SproutGenerationError(
                    f"failed to write destination file '{target_relative.as_posix()}'."
                ) from e

            return

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target_path)
        except OSError as e:
            raise SproutGenerationError(
                f"failed to copy destination file '{target_relative.as_posix()}'."
            ) from e


def render_templates(
    env: Environment | None,
    template_dir: Path,
    destination: Path,
    answers: dict[str, DefaultValue],
    *,
    skip: SkipPredicate | None = None,
    render_paths: bool = False,
    ignore: Sequence[str] | None = None,
    extensions: Sequence[type[Extension]] | None = None,
) -> list[Path]:
    """
    Render a template directory into ``destination``.

    - If ``render_paths`` is True, treat relative paths as Jinja templates and render them with
      ``answers`` (useful for names like ``"{{ package_name }}"``).
    - ``ignore`` is a list of glob patterns (matched against file name) and special names to skip.
    """
    if env is None:
        env = build_environment(template_dir, extensions=extensions or ())

    renderer = TemplateRenderer(
        env=env,
        template_dir=template_dir,
        destination=destination,
        answers=answers,
        skip=skip,
        render_paths=render_paths,
        ignore=ignore,
    )

    return renderer.render()


__all__ = ["TemplateRenderer", "render_templates"]
