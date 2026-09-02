from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from rich.text import Text

from sprout.errors import SproutGenerationError
from sprout.extensions.environment import build_environment
from sprout.manifest import (
    ApplyCallable,
    CreatedPaths,
    Manifest,
    ManifestContext,
    TitleCallable,
)
from sprout.manifest_loader import (
    invoke_context_hook,
    normalize_apply_result,
    resolve_questions,
)
from sprout.prompt.question import DefaultValue
from sprout.prompt.session import collect_answers, confirm_overwrite
from sprout.prompt.style import Style
from sprout.prompt.terminal import console
from sprout.renderer import render_templates


def ensure_destination(path: Path, *, force: bool, style: Style | None = None) -> None:
    """
    Ensure destination directory exists and confirm overwrites when needed.

    Args:
        path (Path): Destination directory path.
        force (bool): Whether to skip overwrite confirmation for non-empty directories.
        style (Style | None): Optional style overrides used for confirmation prompts.

    Raises:
        SproutGenerationError: If `path` points to a file or overwrite confirmation is declined.
    """
    style = style or Style()

    try:
        destination_exists = path.exists()
        if destination_exists and path.is_file():
            raise SproutGenerationError(
                f"destination '{path}' is a file. Provide a directory path."
            )

        if not destination_exists:
            path.mkdir(parents=True, exist_ok=True)
            return

        if not force and any(path.iterdir()):
            console.print(Text(f"Destination '{path}' is not empty.", style="bold yellow"))
            if not confirm_overwrite(path, style=style):
                raise SproutGenerationError("aborted by user.")
    except OSError as e:
        raise SproutGenerationError(f"failed to prepare destination '{path}'.") from e


def summarize(created: Sequence[Path], destination: Path | None = None) -> None:
    """
    Print a summary of generated relative file paths.

    Args:
        created (Sequence[Path]): Created paths relative to the destination directory.
        destination (Path | None): Directory where files were generated.
    """
    if not created:
        return

    heading = "\nGenerated files"
    if destination is not None:
        heading = f"{heading} in {destination}"

    console.print(Text(heading, style="white"), soft_wrap=True)

    for path in created:
        console.print(Text(f"  • {path}", style="white"))


def resolve_template_directory(root: Path, declared: str | Path | None) -> Path:
    if declared is None or (isinstance(declared, str) and declared.strip() == ""):
        return (root / "template").resolve()

    path = Path(declared)

    return path if path.is_absolute() else (root / path).resolve()


class ManifestExecution:
    def __init__(
        self,
        manifest: Manifest,
        *,
        template_dir: Path,
        destination: Path,
        force: bool = False,
        initial_answers: dict[str, DefaultValue] | None = None,
        summary: Callable[[Sequence[Path]], None] | None = None,
    ) -> None:
        self.manifest = manifest
        self.template_root = template_dir
        self.destination = destination
        self.force = force
        self.initial_answers = initial_answers
        self.summary = summary
        self.style = manifest.style or Style()
        self.actual_template_dir = resolve_template_directory(
            self.template_root,
            manifest.template_dir,
        )
        self.env = build_environment(
            self.actual_template_dir,
            extensions=manifest.extensions or (),
        )
        self.answers: dict[str, DefaultValue] = {}

    def execute(self) -> tuple[dict[str, DefaultValue], Sequence[Path] | None]:
        display_title(
            self.manifest.title,
            context=self._context(),
        )

        questions = resolve_questions(self.manifest.questions, self.env, self.destination)
        self.answers = collect_answers(
            questions,
            style=self.style,
            initial_answers=self.initial_answers,
        )
        ensure_destination(self.destination, force=self.force, style=self.style)

        created = self._create_files()
        if created is None:
            return self.answers, None

        created_paths = normalize_created_paths(created, self.destination)
        self._summarize_created(created_paths)

        return self.answers, created_paths

    def _context(self) -> ManifestContext:
        return ManifestContext(
            env=self.env,
            template_dir=self.actual_template_dir,
            template_root=self.template_root,
            destination=self.destination,
            answers=self.answers,
            style=self.style,
        )

    def _create_files(self) -> CreatedPaths:
        if self.manifest.apply is not None:
            return normalize_apply_result(self.manifest.apply(self._context()))
        if not self.actual_template_dir.exists():
            raise SproutGenerationError(
                f"Template directory not found. Expected {self.actual_template_dir} to exist."
            )

        return render_templates(
            self.env,
            self.actual_template_dir,
            self.destination,
            self.answers,
            skip=self.manifest.skip,
            render_paths=True,
        )

    def _summarize_created(self, created_paths: Sequence[Path]) -> None:
        if not created_paths:
            console.print(Text("No files were generated.", style="yellow"))
            return

        if self.summary:
            self.summary(created_paths)
            return

        summarize(created_paths, self.destination)


def execute_manifest(
    manifest: Manifest,
    *,
    template_dir: Path,
    destination: Path,
    force: bool = False,
    initial_answers: dict[str, DefaultValue] | None = None,
    summary: Callable[[Sequence[Path]], None] | None = None,
) -> tuple[dict[str, DefaultValue], Sequence[Path] | None]:
    """
    Execute a manifest workflow and return answers with created paths.

    Args:
        manifest (Manifest): Loaded manifest definition to execute.
        template_dir (Path): Template root that contains `sprout.py` and template files.
        destination (Path): Output directory for generated files.
        force (bool): Whether to skip overwrite confirmation for non-empty destinations.
        initial_answers (dict[str, DefaultValue] | None): Optional pre-filled answers keyed by question key.
        summary (Callable[[Sequence[Path]], None] | None): Optional callback used to print a
            generation summary.

    Raises:
        SproutError: If manifest validation or project generation fails.
    """
    return ManifestExecution(
        manifest,
        template_dir=template_dir,
        destination=destination,
        force=force,
        initial_answers=initial_answers,
        summary=summary,
    ).execute()


def normalize_created_paths(created: Sequence[Path | str], destination: Path) -> list[Path]:
    results: list[Path] = []
    for item in created:
        if isinstance(item, Path) and not item.is_absolute():
            results.append(item)
            continue

        path = Path(item)
        if path.is_absolute():
            try:
                path = path.relative_to(destination)
            except ValueError:
                pass

        results.append(path)

    return results


def invoke_apply(
    apply_fn: ApplyCallable,
    *,
    context: ManifestContext,
) -> CreatedPaths:
    result = invoke_context_hook(apply_fn, context, hook_name="apply")

    return normalize_apply_result(result)


def display_title(
    title: str | TitleCallable | None,
    *,
    context: ManifestContext,
) -> None:
    if title is None:
        return

    if isinstance(title, str):
        console.print(title)
        return

    result = title(context)
    if result is not None:
        console.print(result)


__all__ = [
    "ManifestExecution",
    "ensure_destination",
    "execute_manifest",
    "normalize_created_paths",
    "render_templates",
    "resolve_template_directory",
    "summarize",
]
