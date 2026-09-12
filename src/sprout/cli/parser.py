from __future__ import annotations

import argparse
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from interfacy.argparse_backend.argument_parser import ArgumentParser, InterfacyHelpFormatter

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
    description = question.prompt.strip()
    if description.endswith("?"):
        description = description[:-1].strip()

    if question.help:
        description = f"{description} - {question.help.strip()}"

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


class BooleanPairAction(argparse.Action):
    """Store mutually exclusive boolean flags on a single argument entry."""

    def __init__(
        self,
        option_strings: Sequence[str],
        dest: str,
        default: object = argparse.SUPPRESS,
        help: str | None = None,  # noqa: A002
        **_kwargs: object,
    ) -> None:
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            nargs=0,
            default=default,
            help=help,
        )

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        del values
        current = "no" if option_string and option_string.startswith("--no-") else "yes"
        prior = getattr(namespace, self.dest, None)
        if prior is not None and prior != current:
            parser.error(f"argument {option_string}: not allowed with conflicting boolean option")
        setattr(namespace, self.dest, current)
        if "__" in self.dest:
            orig = self.dest.split("__")[-1]
            setattr(namespace, orig, current)


class SproutHelpFormatter(InterfacyHelpFormatter):
    """Custom help formatter rendering boolean flag pairs as --[no-]flag and capitalized sections."""

    def _format_action_invocation(self, action: argparse.Action) -> str:
        if isinstance(action, BooleanPairAction):
            positive = next((f for f in action.option_strings if not f.startswith("--no-")), None)
            if positive:
                return f"--[no-]{positive.removeprefix('--')}"

        return super()._format_action_invocation(action)

    def start_section(self, heading: str | None) -> None:
        if heading not in (None, argparse.SUPPRESS):
            text = heading.strip()
            heading = text[:1].upper() + text[1:]

        return super().start_section(heading)

    def _format_usage(
        self,
        usage: str | None,
        actions: Iterable[argparse.Action],
        groups: Iterable[argparse._MutuallyExclusiveGroup],
        prefix: str | None,
    ) -> str:
        if prefix is None or prefix.lower().startswith("usage:"):
            prefix = "Usage: "
        if isinstance(usage, str) and usage.lower().startswith("usage:"):
            usage = re.sub(r"^usage:\s*", "", usage, flags=re.IGNORECASE)

        return super()._format_usage(usage, actions, groups, prefix)


def _format_default_value(default: object, key: str | None = None) -> str | None:
    if default is None or default == "":
        return None
    if key in ("author_name", "author_email"):
        return None
    if isinstance(default, (list, tuple)):
        if not default:
            return None
        return ", ".join(str(item) for item in default)
    text = str(default)
    if _HELP_PROBE_DESTINATION in text or "sprout-help-destination" in text:
        return None
    return text


def _boolean_default_text(default: object) -> str | None:
    if default in ("yes", True):
        return "yes"
    if default in ("no", False):
        return "no"

    return None


def _add_boolean_question_flags(
    container: argparse._ActionsContainer,
    *,
    flag: str,
    dest: str,
    help_text: str,
    question: Question,
) -> None:
    negative_flag = f"--no-{flag.removeprefix('--')}"
    default_text = _boolean_default_text(question.default)
    if default_text is not None:
        help_text = f"{help_text} [default: {default_text}]"

    container.add_argument(
        flag,
        negative_flag,
        dest=dest,
        action=BooleanPairAction,
        help=help_text,
        default=argparse.SUPPRESS,
    )


def _categorize_question(key: str) -> str:
    cleaned = key.lower()
    if any(k in cleaned for k in ("git_", "github_repo", "create_github", "create_git")):
        return "git"
    if any(
        k in cleaned
        for k in (
            "license",
            "actions",
            "workflows",
            "badges",
            "setup_",
            "include_",
            "publish_to",
        )
    ):
        return "features"
    if cleaned in ("author_name", "author_email", "description", "repository_url", "homepage"):
        return "metadata"

    return "project"


_METAVAR_EXACT_MAP: dict[str, str] = {
    "description": "<text>",
    "desc": "<text>",
    "summary": "<text>",
    "prompt": "<text>",
    "name": "<name>",
    "pkg": "<name>",
    "crate": "<name>",
    "package": "<name>",
    "email": "<email>",
    "mail": "<email>",
    "url": "<url>",
    "homepage": "<url>",
    "website": "<url>",
    "repo_url": "<url>",
    "version": "<version>",
    "msrv": "<version>",
    "type": "<type>",
    "kind": "<kind>",
    "path": "<path>",
    "dir": "<path>",
    "directory": "<path>",
    "edition": "<edition>",
    "policy": "<policy>",
    "license": "<license>",
    "visibility": "<visibility>",
}

_METAVAR_SUFFIX_MAP: tuple[tuple[str, str], ...] = (
    ("_name", "<name>"),
    ("_email", "<email>"),
    ("_url", "<url>"),
    ("_version", "<version>"),
    ("_type", "<type>"),
    ("_kind", "<kind>"),
    ("_path", "<path>"),
    ("_edition", "<edition>"),
    ("_policy", "<policy>"),
    ("_license", "<license>"),
    ("_visibility", "<visibility>"),
)


def _derive_metavar(key: str) -> str:
    cleaned = key.lower()
    if cleaned in _METAVAR_EXACT_MAP:
        return _METAVAR_EXACT_MAP[cleaned]

    if "workflow" in cleaned or "action" in cleaned:
        return "<workflow>"

    for suffix, metavar in _METAVAR_SUFFIX_MAP:
        if cleaned.endswith(suffix):
            return metavar

    last = key.rsplit("_", maxsplit=1)[-1].strip().lower()

    return f"<{last}>" if last else "<value>"


def _metavar_for_question(question: Question) -> str:
    explicit = getattr(question, "metavar", None)
    if isinstance(explicit, str) and explicit.strip():
        val = explicit.strip()
        if not val.startswith("<") and not val.endswith(">"):
            return f"<{val.lower()}>"
        return val

    return _derive_metavar(question.key)


def build_cli_parser(
    prepared: PreparedTemplate | None,
    *,
    help_note: str | None = None,
    trusted_templates: Sequence[TrustedTemplate] | None = None,
) -> ArgumentParser:
    parser = ArgumentParser(
        prog="sprout",
        description="Create projects from Sprout templates.",
        formatter_class=SproutHelpFormatter,
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
        usage="sprout new [options] TEMPLATE DESTINATION" if prepared is not None else None,
        formatter_class=SproutHelpFormatter,
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

    if prepared is not None:
        _add_question_flags_to_parser(new_parser, prepared)

    return parser


def _add_question_flags_to_parser(
    new_parser: ArgumentParser,
    prepared: PreparedTemplate,
) -> None:
    used_dests = {"template", "destination", "force", "help"}
    groups: dict[str, argparse._ArgumentGroup] = {
        "project": new_parser.add_argument_group("project"),
        "metadata": new_parser.add_argument_group("metadata"),
        "git": new_parser.add_argument_group("git"),
        "features": new_parser.add_argument_group("features"),
    }

    for question in prepared.questions:
        dest = sanitize_question_key(question.key)
        if dest in used_dests:
            continue

        used_dests.add(dest)

        category = _categorize_question(question.key)
        target_container: argparse._ActionsContainer = groups.get(category, new_parser)

        get_nested = getattr(new_parser, "_get_nested_destination", None)
        nested_dest = str(get_nested(dest, store=True)) if callable(get_nested) else dest

        flag = f"--{_flag_from_question_key(question.key)}"
        help_text = _format_question_help(question)
        if (
            prepared.manifest.cli_boolean_style == "flags"
            and not question.multiselect
            and _is_yes_no_question(question)
        ):
            _add_boolean_question_flags(
                target_container,
                flag=flag,
                dest=nested_dest,
                help_text=help_text,
                question=question,
            )
            continue

        choice_values: list[str] | None = None
        if not callable(question.choices):
            choices = question.resolve_choices({})
            if choices:
                choice_values = [value for value, _label in choices]
                if len(choice_values) > 8:
                    choices_summary = (
                        f"{', '.join(choice_values[:5])}, ...; {len(choice_values)} available"
                    )
                else:
                    choices_summary = ", ".join(choice_values)
                help_text = f"{help_text} (choices: {choices_summary})"
        if not _is_yes_no_question(question) and not callable(question.default):
            default_summary = _format_default_value(question.default, key=question.key)
            if default_summary is not None:
                help_text = f"{help_text} [default: {default_summary}]"

        metavar = _metavar_for_question(question)
        if question.multiselect:
            target_container.add_argument(
                flag,
                dest=nested_dest,
                help=help_text,
                default=argparse.SUPPRESS,
                type=str,
                choices=choice_values,
                action="append",
                metavar=metavar,
            )
            continue

        target_container.add_argument(
            flag,
            dest=nested_dest,
            help=help_text,
            default=argparse.SUPPRESS,
            type=str,
            choices=choice_values,
            metavar=metavar,
        )


__all__ = [
    "CliInvocation",
    "PreparedTemplate",
    "build_cli_parser",
    "prepare_template_for_cli",
    "registered_templates_for_new_help",
    "resolve_registered_template",
    "sanitize_question_key",
]
