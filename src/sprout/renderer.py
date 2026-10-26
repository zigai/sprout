from __future__ import annotations

import fnmatch
import shutil
import tempfile
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
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

    def render(self, *, prepare: Callable[[], None] | None = None) -> list[Path]:
        if prepare is not None:
            with self._stage():
                prepare()
                return self.render()

        with self._stage() as (planned, staging):
            backup_directory = tempfile.TemporaryDirectory(
                prefix=".sprout-backups-",
                dir=self.destination,
                delete=False,
            )
            backups = Path(backup_directory.name)
            restore_failed = False
            written: list[tuple[Path, Path | None]] = []
            try:
                for index, (source, target_relative, _relative_str) in enumerate(planned):
                    target = self._destination_path(target_relative)

                    target.parent.mkdir(parents=True, exist_ok=True)
                    backup = backups / str(index) if target.exists() else None
                    if backup is not None:
                        shutil.copy2(target, backup)
                        if source.suffix == ".jinja":
                            shutil.copymode(target, staging / target_relative)

                    written.append((target, backup))
                    (staging / target_relative).replace(target)
            except BaseException as e:
                errors: list[BaseException] = [e, *self._restore_files(written)]
                restore_failed = len(errors) > 1

                if len(errors) > 1:
                    raise BaseExceptionGroup(
                        f"Failed to restore generated destination files; backups remain at {backups}.",
                        errors,
                    ) from None

                raise
            finally:
                if not restore_failed:
                    backup_directory.cleanup()

        return [target_relative for _source, target_relative, _relative_str in planned]

    def _destination_path(self, relative: Path) -> Path:
        target = (self.destination / relative).resolve()
        if not target.is_relative_to(self.destination.resolve()):
            raise SproutGenerationError(f"'{relative}' must stay within the destination directory.")

        return target

    def _restore_files(self, written: Sequence[tuple[Path, Path | None]]) -> list[OSError]:
        errors: list[OSError] = []
        for target, backup in reversed(written):
            try:
                if backup is None:
                    target.unlink(missing_ok=True)
                else:
                    backup.replace(target)
            except OSError as e:
                errors.append(e)

        return errors

    @contextmanager
    def _stage(self) -> Generator[tuple[list[tuple[Path, Path, str]], Path]]:
        planned: list[tuple[Path, Path, str]] = []
        targets: dict[Path, str] = {}

        for source in sorted(self.template_dir.rglob("*")):
            if source.is_dir() or _should_ignore_path(source, self.ignore_patterns):
                continue

            relative = source.relative_to(self.template_dir)
            relative_str = relative.as_posix()
            if self.skip and self.skip(relative_str, self.answers):
                continue

            target_relative = self._resolve_target_relative(source, relative)
            target_path = (self.destination / target_relative).resolve()
            if target_path in targets:
                raise SproutGenerationError(
                    f"'{targets[target_path]}' and '{relative_str}' map to the same destination file."
                )

            targets[target_path] = relative_str
            planned.append((source, target_relative, relative_str))

        try:
            self.destination.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".sprout-", dir=self.destination) as directory:
                staging = Path(directory)
                self._stage_files(planned, staging)
                yield planned, staging
        except OSError as e:
            raise SproutGenerationError("failed to write generated files.") from e

    def _stage_files(
        self,
        planned: Sequence[tuple[Path, Path, str]],
        staging: Path,
    ) -> None:
        for source, target_relative, relative_str in planned:
            target = staging / target_relative
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch(exist_ok=False)
            except FileExistsError as e:
                raise SproutGenerationError(
                    f"'{relative_str}' conflicts with another destination path."
                ) from e

            self._render_source_file(source, target_relative, relative_str, destination=staging)

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

        if (
            target_relative.is_absolute()
            or ".." in target_relative.parts
            or not (self.destination / target_relative)
            .resolve()
            .is_relative_to(self.destination.resolve())
        ):
            raise SproutGenerationError(
                f"rendered path for '{relative.as_posix()}' must stay within the destination directory."
            )

        if (self.destination / target_relative).is_dir():
            raise SproutGenerationError(
                f"destination '{target_relative}' is a directory, not a file."
            )

        for parent in (self.destination / target_relative).parents:
            if parent == self.destination:
                break

            if parent.exists() and not parent.is_dir():
                raise SproutGenerationError(f"destination parent '{parent}' is not a directory.")

        return target_relative

    def _render_source_file(
        self,
        source: Path,
        target_relative: Path,
        relative_str: str,
        *,
        destination: Path,
    ) -> None:
        target_path = destination / target_relative
        if source.suffix == ".jinja":
            template = self.env.get_template(relative_str)
            rendered = template.render(**self.answers)
            try:
                target_path.write_text(rendered, encoding="utf-8")
            except OSError as e:
                raise SproutGenerationError(
                    f"failed to write destination file '{target_relative.as_posix()}'."
                ) from e

            return

        try:
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
    prepare: Callable[[], None] | None = None,
) -> list[Path]:
    """
    Render a template directory into ``destination``.

    - If ``render_paths`` is True, treat relative paths as Jinja templates and render them with
      ``answers`` (useful for names like ``"{{ package_name }}"``).
    - ``ignore`` is a list of glob patterns (matched against file name) and special names to skip.
    - ``prepare`` runs after staged validation and before final rendering and writing.
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

    return renderer.render(prepare=prepare)


__all__ = ["TemplateRenderer", "render_templates"]
