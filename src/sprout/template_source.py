from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
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

        url = _normalise_git_url(template_src)
        git_executable = _resolve_git_executable()
        try:
            temporary_directory = tempfile.TemporaryDirectory(prefix="sprout-template-")
        except OSError as e:
            raise SproutTemplateSourceError(
                "failed to create temporary directory for template clone."
            ) from e

        target_dir = Path(temporary_directory.name) / "template"

        try:
            subprocess.run(  # noqa: S603 - validated git clone invocation
                [git_executable, "clone", "--depth", "1", "--", url, str(target_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:  # pragma: no cover - external dependency
            _cleanup_failed_clone(temporary_directory, e)
            raise SproutTemplateSourceError("failed to clone remote template.") from e
        except OSError as e:
            _cleanup_failed_clone(temporary_directory, e)
            raise SproutTemplateSourceError(
                "failed to launch git clone for remote template."
            ) from e
        except BaseException as error:
            _cleanup_failed_clone(temporary_directory, error)
            raise

        return cls(target_dir, temporary_directory)

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


def _normalise_git_url(template_src: str) -> str:
    cleaned = template_src.strip()
    if cleaned.startswith(("http://", "https://", "git@", "ssh://")):
        return cleaned

    if cleaned.count("/") == 1 and " " not in cleaned:
        owner, repo = cleaned.split("/", maxsplit=1)
        repo_name = repo if repo.endswith(".git") else f"{repo}.git"
        return f"https://github.com/{owner}/{repo_name}"

    return cleaned


__all__ = ["TemplateSource"]
