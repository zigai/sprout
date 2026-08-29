from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from rich.table import Table
from rich.text import Text

from sprout.cli.parser import (
    PreparedTemplate,
    resolve_registered_template,
    sanitize_question_key,
)
from sprout.execution import execute_manifest, normalize_created_paths, summarize
from sprout.manifest_loader import load_manifest
from sprout.prompt.question import DefaultValue, Question
from sprout.prompt.session import ask_question
from sprout.prompt.style import Style
from sprout.prompt.terminal import console, supports_live_interaction
from sprout.registry import (
    TemplateRegistry,
    TrustedTemplate,
    derive_template_name,
    normalize_template_name,
    normalize_template_source,
)
from sprout.scaffold import create_template_scaffold
from sprout.template_source import TemplateSource


@dataclass(frozen=True)
class TemplateCliArgs:
    """
    Hold normalized CLI arguments for template execution.

    Attributes:
        template_src (str): Template source path, Git URL, or owner/repo shorthand.
        destination (Path): Absolute destination directory path.
        force (bool): Whether to allow overwriting in a non-empty destination.
    """

    template_src: str
    destination: Path
    force: bool = False


def generate(
    template: str,
    destination: str | Path,
    *,
    force: bool = False,
) -> int:
    """
    Generate a project from a sprout manifest.

    The manifest can define questions and an optional apply hook.

    Args:
        template: path or git repository containing a sprout.py manifest
        destination: target directory for the generated project
        force: overwrite files in the destination directory if they already exist
    """
    return _run_generate(template, destination, force=force, initial_answers=None, prepared=None)


def init_template(directory: str | Path = ".") -> int:
    """Create a minimal Sprout template scaffold."""
    root = Path(directory).expanduser().resolve()
    created = create_template_scaffold(root)
    summarize(normalize_created_paths(created, root), root)

    return 0


def add_template(source: str, *, name: str | None = None) -> int:
    """Add a local or remote template source to the trusted registry."""
    normalized_source = normalize_template_source(source)
    default_name = derive_template_name(normalized_source)
    template_name = (
        normalize_template_name(name) if name is not None else _prompt_template_name(default_name)
    )
    registry = TemplateRegistry()
    existing = registry.find(template_name)
    if existing is not None and not _confirm_template_replace(existing, normalized_source):
        raise SystemExit("template registry was not changed.")

    registry.save(TrustedTemplate(name=template_name, source=normalized_source))
    console.print(
        Text(
            f"Trusted template '{template_name}' now points to {normalized_source}.", style="green"
        )
    )

    return 0


def list_templates() -> int:
    """List trusted template names and their sources."""
    entries = TemplateRegistry().entries()
    if not entries:
        console.print("No trusted templates have been added.")
        return 0

    table = Table(
        box=None,
        collapse_padding=True,
        header_style="",
        pad_edge=False,
        padding=(0, 1),
    )
    table.add_column("Name")
    table.add_column("Source")
    for entry in entries:
        table.add_row(entry.name, entry.source)

    console.print(table)

    return 0


def _prompt_template_name(default_name: str) -> str:
    if not supports_live_interaction():
        raise SystemExit("--name is required when interactive prompting is unavailable.")

    answer = ask_question(
        Question(key="name", prompt="Template name", default=default_name),
        {},
        Style(),
    )
    if not isinstance(answer, str):
        raise SystemExit("template name must be text.")

    return normalize_template_name(answer)


def _confirm_template_replace(existing: TrustedTemplate, source: str) -> bool:
    if not supports_live_interaction():
        raise SystemExit(
            f"trusted template '{existing.name}' already exists; interactive confirmation is required."
        )

    answer = ask_question(
        Question.yes_no(
            key="replace",
            prompt=f"Replace trusted template '{existing.name}' with {source}?",
            default=False,
        ),
        {},
        Style(),
    )

    return answer is True


def _run_generate(
    template: str,
    destination: str | Path,
    *,
    force: bool,
    initial_answers: dict[str, DefaultValue] | None,
    prepared: PreparedTemplate | None,
) -> int:
    destination_path = Path(destination).expanduser().resolve()
    args = TemplateCliArgs(
        template_src=template,
        destination=destination_path,
        force=force,
    )
    source: TemplateSource | None = None
    try:
        if prepared is not None and prepared.template_src == template:
            template_dir = prepared.template_dir
            manifest = prepared.manifest
        else:
            source = TemplateSource.from_source(args.template_src)
            template_dir = source.root
            manifest = load_manifest(template_dir)

        execute_manifest(
            manifest,
            template_dir=template_dir,
            destination=args.destination,
            force=args.force,
            initial_answers=initial_answers,
        )
    except KeyboardInterrupt:  # pragma: no cover - interactive
        console.print(Text("Aborted by user.", style="bold red"))
        return 1
    finally:
        if source is not None:
            source.close()

    return 0


def _run_init_command(values: Mapping[str, object]) -> int:
    directory = values.get("directory", ".")
    if not isinstance(directory, str):
        raise SystemExit("scaffold directory must be a path.")

    return init_template(directory)


def _run_add_command(values: Mapping[str, object]) -> int:
    source = values.get("source")
    name = values.get("name")

    if not isinstance(source, str):
        raise SystemExit("template source is required.")
    if name is not None and not isinstance(name, str):
        raise SystemExit("template name must be text.")

    return add_template(source, name=name)


def _run_new_command(
    values: Mapping[str, object],
    prepared: PreparedTemplate | None,
) -> int:
    template = values.get("template")
    destination = values.get("destination")
    if not isinstance(template, str) or not isinstance(destination, str):
        raise SystemExit("template and destination are required.")

    cli_answers: dict[str, DefaultValue] = {}
    if prepared is not None:
        for question in prepared.questions:
            dest = sanitize_question_key(question.key)
            if dest in values:
                cli_answers[question.key] = values[dest]

    return _run_generate(
        resolve_registered_template(template),
        destination,
        force=bool(values.get("force", False)),
        initial_answers=cli_answers or None,
        prepared=prepared,
    )


def dispatch_command(
    command: str,
    values: Mapping[str, object],
    prepared: PreparedTemplate | None,
) -> int:
    if command == "init":
        return _run_init_command(values)
    if command == "add":
        return _run_add_command(values)
    if command == "new":
        return _run_new_command(values, prepared)
    if command == "list":
        return list_templates()

    raise SystemExit(f"unknown command: {command}")


__all__ = [
    "TemplateCliArgs",
    "add_template",
    "dispatch_command",
    "generate",
    "init_template",
    "list_templates",
]
