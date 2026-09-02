from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from interfacy.argparse_backend.argument_parser import ArgumentParser

from sprout.execution import resolve_template_directory
from sprout.extensions.environment import build_environment
from sprout.manifest import Manifest
from sprout.manifest_loader import load_manifest, resolve_questions
from sprout.prompt.question import YES_NO_CHOICES, Question, parse_yes_no
from sprout.registry import TemplateRegistry, TrustedTemplate
from sprout.template_source import TemplateSource


def resolve_registered_template(template: str) -> str:
    entry = TemplateRegistry().find(template)

    return entry.source if entry is not None else template


@dataclass(frozen=True)
class PreparedTemplate:
    """
    Hold preloaded manifest state used for CLI argument parsing and generation.

    Attributes:
        template_src (str): Template source used for this prepared manifest.
        source (TemplateSource): Owner of the resolved local template directory.
        manifest (Manifest): Loaded manifest definition.
        questions (Sequence[Question]): Resolved questions available for CLI flags.
    """

    template_src: str
    source: TemplateSource
    manifest: Manifest
    questions: Sequence[Question]

    @property
    def template_dir(self) -> Path:
        return self.source.root

    def close(self) -> None:
        self.source.close()


@dataclass(frozen=True)
class CliInvocation:
    template_src: str | None
    destination: Path | None
    help_requested: bool

    @classmethod
    def from_args(cls, args: Sequence[str] | None) -> CliInvocation:
        command_args = args[1:] if args and args[0] == "new" else None
        template_src, destination = _extract_template_destination(command_args)

        return cls(
            template_src=template_src,
            destination=destination,
            help_requested=_has_help_option(args),
        )


def sanitize_question_key(key: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]", "_", key)
    if not cleaned:
        cleaned = "question"

    if cleaned[0].isdigit():
        cleaned = f"q_{cleaned}"

    return cleaned


_FLAG_ONLY_OPTIONS = {"-h", "--help", "--force"}
_HELP_OPTIONS = {"-h", "--help"}
_HELP_PROBE_DESTINATION = "__sprout_help_destination__"
_HELP_PRELOAD_FALLBACK_NOTE = (
    "Template-specific options could not be resolved from template-only help. "
    "Run sprout new <template> <destination> --help for full template-aware options."
)


def _consume_optional_value(args: Sequence[str], index: int) -> int:
    option = args[index]
    if option in _FLAG_ONLY_OPTIONS or "=" in option:
        return index + 1

    next_index = index + 1
    if next_index >= len(args):
        return next_index

    next_arg = args[next_index]
    if next_arg == "--" or next_arg.startswith("-"):
        return index + 1

    return index + 2


def _has_help_option(args: Sequence[str] | None) -> bool:
    return any(value in _HELP_OPTIONS for value in args) if args else False


def _extract_template_destination(
    args: Sequence[str] | None,
) -> tuple[str | None, Path | None]:
    if not args:
        return None, None

    positional: list[str] = []
    end_of_opts = False
    i = 0
    while i < len(args) and len(positional) < 2:
        arg_value = args[i]
        if not end_of_opts and arg_value == "--":
            end_of_opts = True
            i += 1

            continue

        if not end_of_opts and arg_value.startswith("-"):
            i = _consume_optional_value(args, i)
            continue

        positional.append(arg_value)

        i += 1

    template = positional[0] if positional else None
    destination = positional[1] if len(positional) > 1 else None
    if destination is None:
        return template, None

    return template, Path(destination).expanduser().resolve()


def _load_questions_for_cli(template_src: str, destination: Path) -> PreparedTemplate:
    source = TemplateSource.from_source(template_src)
    try:
        template_dir = source.root
        manifest = load_manifest(template_dir)
        actual_template_dir = resolve_template_directory(template_dir, manifest.template_dir)
        env = build_environment(actual_template_dir, extensions=manifest.extensions or ())
        questions = resolve_questions(manifest.questions, env, destination)
    except (Exception, KeyboardInterrupt, SystemExit):
        source.close()
        raise

    return PreparedTemplate(
        template_src=template_src,
        source=source,
        manifest=manifest,
        questions=questions,
    )


def prepare_template_for_cli(
    invocation: CliInvocation,
) -> tuple[PreparedTemplate | None, str | None]:
    if invocation.template_src and invocation.destination is not None:
        template_src = resolve_registered_template(invocation.template_src)
        return _load_questions_for_cli(template_src, invocation.destination), None

    if not invocation.template_src or not invocation.help_requested:
        return None, None

    try:
        probe_destination = (Path.cwd() / _HELP_PROBE_DESTINATION).resolve()
        template_src = resolve_registered_template(invocation.template_src)
        return _load_questions_for_cli(template_src, probe_destination), None
    except SystemExit:
        return None, _HELP_PRELOAD_FALLBACK_NOTE
    except Exception:  # noqa: BLE001 - help output should not fail on preload errors.
        return None, _HELP_PRELOAD_FALLBACK_NOTE


def registered_templates_for_new_help(
    args: Sequence[str],
    invocation: CliInvocation,
) -> tuple[TrustedTemplate, ...] | None:
    if (
        not args
        or args[0] != "new"
        or not invocation.help_requested
        or invocation.template_src is not None
    ):
        return None

    return TemplateRegistry().entries()


def _format_trusted_templates_help(templates: Sequence[TrustedTemplate]) -> str:
    if not templates:
        return "No trusted templates have been added. Use sprout add to add one."

    entries = "\n".join(f"  {template.name}: {template.source}" for template in templates)

    return f"Trusted templates added with sprout add:\n{entries}"


def _format_question_help(question: Question) -> str:
    description = question.prompt
    if question.help:
        description = f"{description} - {question.help}"

    if question.multiselect:
        description = f"{description} (multiple values allowed)"

    return description[:1].upper() + description[1:]


def _flag_from_question_key(key: str) -> str:
    cleaned = key.strip().replace("_", "-")
    cleaned = re.sub(r"[^0-9a-zA-Z-]", "-", cleaned)
    cleaned = cleaned.strip("-")

    return cleaned.lower() or "question"


def _is_yes_no_question(question: Question) -> bool:
    choices = question.resolve_choices({}) if not callable(question.choices) else None

    return question.parser is parse_yes_no and list(choices or ()) == list(YES_NO_CHOICES)


def _add_boolean_question_flags(
    parser: ArgumentParser,
    *,
    flag: str,
    dest: str,
    help_text: str,
) -> None:
    negative_flag = f"--no-{flag.removeprefix('--')}"
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        flag,
        dest=dest,
        help=f"{help_text} (yes)",
        default=argparse.SUPPRESS,
        action="store_const",
        const="yes",
    )
    group.add_argument(
        negative_flag,
        dest=dest,
        help=f"{help_text} (no)",
        default=argparse.SUPPRESS,
        action="store_const",
        const="no",
    )


def build_cli_parser(
    prepared: PreparedTemplate | None,
    *,
    help_note: str | None = None,
    trusted_templates: Sequence[TrustedTemplate] | None = None,
) -> ArgumentParser:
    parser = ArgumentParser(
        prog="sprout",
        description="Create projects from Sprout templates.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser(
        "init",
        help="Create a minimal Sprout template scaffold.",
        description="Create a minimal Sprout template scaffold.",
    )
    init_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory where the scaffold should be created",
    )

    add_parser = commands.add_parser(
        "add",
        help="Add a source to the trusted template registry.",
        description="Add a source to the trusted template registry.",
    )
    add_parser.add_argument(
        "source",
        help="Local path, Git URL, or GitHub owner/repo shorthand",
    )
    add_parser.add_argument(
        "--name",
        help="Trusted template name; prompts when omitted",
    )

    new_description = "Generate a project from a Sprout manifest."
    if trusted_templates is not None:
        new_description = (
            f"{new_description}\n\n{_format_trusted_templates_help(trusted_templates)}"
        )

    if help_note:
        new_description = f"{new_description}\n\n{help_note}"
    new_parser = commands.add_parser(
        "new",
        help="Generate a project from a template.",
        description=new_description,
    )
    new_parser.add_argument(
        "template",
        help="Trusted name, local path, or Git repository containing sprout.py",
    )
    new_parser.add_argument(
        "destination",
        help="Target directory for the generated project",
    )
    new_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite files in the destination directory if they already exist",
    )

    commands.add_parser(
        "list",
        help="List trusted templates.",
        description="List trusted template names and their sources.",
    )

    if prepared is None:
        return parser

    used_dests = {"template", "destination", "force", "help"}
    for question in prepared.questions:
        dest = sanitize_question_key(question.key)
        if dest in used_dests:
            continue

        used_dests.add(dest)

        flag = f"--{_flag_from_question_key(question.key)}"
        help_text = _format_question_help(question)
        if (
            prepared.manifest.cli_boolean_style == "flags"
            and not question.multiselect
            and _is_yes_no_question(question)
        ):
            _add_boolean_question_flags(
                new_parser,
                flag=flag,
                dest=dest,
                help_text=help_text,
            )
            continue

        choice_values: list[str] | None = None
        if not callable(question.choices):
            choices = question.resolve_choices({})
            if choices:
                choice_values = [value for value, _label in choices]
                help_text = f"{help_text} (choices: {', '.join(choice_values)})"

        if question.multiselect:
            new_parser.add_argument(
                flag,
                dest=dest,
                help=help_text,
                default=argparse.SUPPRESS,
                type=str,
                choices=choice_values,
                action="append",
            )
            continue

        new_parser.add_argument(
            flag,
            dest=dest,
            help=help_text,
            default=argparse.SUPPRESS,
            type=str,
            choices=choice_values,
        )

    return parser


__all__ = [
    "CliInvocation",
    "PreparedTemplate",
    "build_cli_parser",
    "prepare_template_for_cli",
    "registered_templates_for_new_help",
    "resolve_registered_template",
    "sanitize_question_key",
]
