from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Self

from sprout.errors import SproutTemplateSourceError


class TemplateSource:
    """Own a resolved local template root and any temporary clone behind it."""

    def __init__(
        self,
        root: Path,
        temporary_directory: tempfile.TemporaryDirectory[str] | None = None,
    ) -> None:
        self.root = root
        self._temporary_directory = temporary_directory

    @classmethod
    def from_source(cls, template_src: str) -> TemplateSource:
        candidate = Path(template_src).expanduser()
        if candidate.exists():
            if not candidate.is_dir():
                raise SproutTemplateSourceError(
                    f"template source {template_src} must be a directory."
                )

            return cls(candidate.resolve())

        url, subdirectory = _parse_remote_source(template_src)
        git_executable = _resolve_git_executable()
        try:
            temporary_directory = tempfile.TemporaryDirectory(prefix="sprout-template-")
        except OSError as e:
            raise SproutTemplateSourceError(
                "failed to create temporary directory for template clone."
            ) from e

        clone_dir = Path(temporary_directory.name) / "template"

        try:
            _clone(git_executable, url, clone_dir, subdirectory)
            root = _resolve_subdirectory(clone_dir, subdirectory)
        except BaseException as error:
            _cleanup_failed_clone(temporary_directory, error)
            raise

        return cls(root, temporary_directory)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        e: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, e, traceback
        self.close()

    def close(self) -> None:
        temporary_directory = self._temporary_directory
        if temporary_directory is None:
            return

        self._temporary_directory = None
        temporary_directory.cleanup()


def _cleanup_failed_clone(
    temporary_directory: tempfile.TemporaryDirectory[str],
    error: BaseException,
) -> None:
    try:
        temporary_directory.cleanup()
    except OSError:
        error.add_note("failed to clean up temporary template directory.")


def _resolve_git_executable() -> str:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise SproutTemplateSourceError("git is required to clone remote templates.")

    return git_executable


def _clone(
    git_executable: str,
    url: str,
    target_dir: Path,
    subdirectory: PurePosixPath | None,
) -> None:
    clone_args = ["clone", "--depth", "1"]
    if subdirectory is not None:
        clone_args += ["--filter=blob:none", "--sparse"]

    commands = [[git_executable, *clone_args, "--", url, str(target_dir)]]
    if subdirectory is not None:
        commands.append(
            [
                git_executable,
                "-C",
                str(target_dir),
                "sparse-checkout",
                "set",
                "--skip-checks",
                "--",
                subdirectory.as_posix(),
            ]
        )

    for command in commands:
        try:
            subprocess.run(  # noqa: S603 - validated git clone invocation
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise SproutTemplateSourceError("failed to clone remote template.") from e
        except OSError as e:
            raise SproutTemplateSourceError(
                "failed to launch git clone for remote template."
            ) from e


def _resolve_subdirectory(clone_dir: Path, subdirectory: PurePosixPath | None) -> Path:
    if subdirectory is None:
        return clone_dir

    repository_root = clone_dir.resolve()
    root = (clone_dir / subdirectory).resolve()
    if not root.is_relative_to(repository_root):
        raise SproutTemplateSourceError(
            f"template path {subdirectory} resolves outside the repository."
        )
    if not root.is_dir():
        raise SproutTemplateSourceError(
            f"template path {subdirectory} is not a directory in the repository."
        )
    if not (root / "sprout.py").is_file():
        raise SproutTemplateSourceError(f"template path {subdirectory} has no sprout.py.")

    return root


def _parse_remote_source(template_src: str) -> tuple[str, PurePosixPath | None]:
    cleaned = template_src.strip()
    shorthand = _parse_github_shorthand(cleaned)
    if shorthand is not None:
        return shorthand

    url, separator, path = cleaned.partition("#")
    if not separator:
        return url, None

    return url, _parse_subdirectory(path, template_src)


def _parse_github_shorthand(source: str) -> tuple[str, PurePosixPath | None] | None:
    if any(character in source for character in " :#\\") or source.startswith(("/", ".", "~")):
        return None

    owner, _, rest = source.partition("/")
    repo, _, path = rest.partition("/")
    if not owner or not repo:
        return None

    repo_name = repo if repo.endswith(".git") else f"{repo}.git"
    url = f"https://github.com/{owner}/{repo_name}"
    if not path:
        return url, None

    return url, _parse_subdirectory(path, source)


def _parse_subdirectory(path: str, template_src: str) -> PurePosixPath:
    subdirectory = PurePosixPath(path.strip().strip("/"))
    if subdirectory.parts in {(), (".",)}:
        raise SproutTemplateSourceError(
            f"template source {template_src} has an empty template path."
        )
    if ".." in subdirectory.parts:
        raise SproutTemplateSourceError(
            f"template path {path} in {template_src} escapes the repository."
        )

    return subdirectory


__all__ = ["TemplateSource"]
