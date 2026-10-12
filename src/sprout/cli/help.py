from __future__ import annotations

import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from interfacy.help import HelpContent, HelpContext, HelpLayout, StandardLayout
from interfacy.schema import Argument, ArgumentKind, Command, ValueShape

USAGE_PREFIX = "Usage: "

_HELP_OPTION_LABEL = "--help"
_HELP_OPTION_DESCRIPTION = "Show this help message and exit"
_NEGATED_PREFIX = "--no-"
_INDENT = 2
_GAP = 2
_MIN_OPTION_COLUMN = 24
_MAX_POSITIONAL_COLUMN = 24
_WRAP_MARGIN = 2


def build_help_layout() -> HelpLayout:
    return StandardLayout(
        include_metavar_in_flag_display=True,
        usage_prefix=USAGE_PREFIX,
        commands_title="Commands:",
        command_indent=_INDENT,
    )


@dataclass(frozen=True)
class SproutHelpRenderer:
    """
    Render capitalized sections, grouped options, and custom usage lines.

    Attributes:
        usages (Mapping[str, str]): Usage text keyed by parser prog, replacing the generated one.
        option_groups (Mapping[str, Sequence[str]]): Option destinations keyed by section title,
            in display order. Options not listed stay in the default options section.
    """

    usages: Mapping[str, str]
    option_groups: Mapping[str, Sequence[str]]

    def __call__(self, context: HelpContext, content: HelpContent) -> str:
        command = context.command
        if command is None:
            raise ValueError("Sprout help can only render command schemas.")

        width = max(context.terminal_width - _WRAP_MARGIN, 20)
        blocks: list[str] = []
        for section in content.sections:
            match section.kind:
                case "usage":
                    custom = self.usages.get(context.prog)
                    blocks.append(section.text if custom is None else f"{USAGE_PREFIX}{custom}")
                case "description":
                    blocks.append(_wrap_description(command.description or section.text, width))
                case "options":
                    blocks.extend(self._argument_blocks(command, width))
                case "positionals":
                    continue
                case _:
                    blocks.append(section.text)

        return "\n\n".join(block.rstrip("\n") for block in blocks if block)

    def _argument_blocks(self, command: Command, width: int) -> list[str]:
        positionals = [
            (_positional_label(argument), argument.help or "")
            for argument in command.arguments
            if argument.kind == ArgumentKind.POSITIONAL
        ]
        options = {
            argument.name: (_option_label(argument), argument.help or "")
            for argument in command.arguments
            if argument.kind == ArgumentKind.OPTION
        }
        grouped_names = {name for names in self.option_groups.values() for name in names}
        default_options = [
            (_HELP_OPTION_LABEL, _HELP_OPTION_DESCRIPTION),
            *(row for name, row in options.items() if name not in grouped_names),
        ]
        option_sections = [("Options", default_options)]
        option_sections.extend(
            (title, [options[name] for name in names if name in options])
            for title, names in self.option_groups.items()
        )

        option_labels = [label for _title, rows in option_sections for label, _help in rows]
        positional_labels = [label for label, _help in positionals]
        all_labels = [*positional_labels, *option_labels]
        longest_option = max(len(label) for label in option_labels)
        longest_label = max(len(label) for label in all_labels)
        positional_column = min(_MAX_POSITIONAL_COLUMN, _INDENT + longest_label + _GAP)
        option_column = min(
            max(_MIN_OPTION_COLUMN, _INDENT + longest_option + _GAP),
            max(_MIN_OPTION_COLUMN, width // 2),
        )

        blocks: list[str] = []
        if positionals:
            blocks.append(
                _render_section("Positional arguments", positionals, positional_column, width)
            )

        blocks.extend(
            _render_section(title, rows, option_column, width)
            for title, rows in option_sections
            if rows
        )

        return blocks


def _positional_label(argument: Argument) -> str:
    label = argument.metavar or argument.name.upper()

    return label if argument.required else f"[{label}]"


def _boolean_pair_name(argument: Argument) -> str | None:
    behavior = argument.boolean_behavior
    if behavior is None:
        return None

    flags = (*behavior.positive_flags, *behavior.negative_flags)
    for flag in flags:
        if not flag.startswith(_NEGATED_PREFIX) and f"{_NEGATED_PREFIX}{flag[2:]}" in flags:
            return flag[2:]

    return None


def _option_label(argument: Argument) -> str:
    pair_name = _boolean_pair_name(argument)
    if pair_name is not None:
        return f"--[no-]{pair_name}"

    if argument.value_shape == ValueShape.FLAG:
        return ", ".join(argument.flags)

    metavar = argument.metavar or argument.name.upper()

    return ", ".join(f"{flag} {metavar}" for flag in argument.flags)


def _wrap_description(text: str, width: int) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue

        indent = line[: len(line) - len(line.lstrip())]
        lines.append(
            textwrap.fill(
                stripped,
                width=width,
                initial_indent=indent,
                subsequent_indent=indent,
                break_long_words=False,
                break_on_hyphens=False,
            )
        )

    return "\n".join(lines)


def _render_section(
    title: str,
    rows: Sequence[tuple[str, str]],
    column: int,
    width: int,
) -> str:
    label_room = column - _INDENT - _GAP
    padding = " " * column
    lines = [f"{title}:"]
    for label, help_text in rows:
        head = " " * _INDENT + label
        wrapped = textwrap.wrap(" ".join(help_text.split()), width=max(width - column, 20))
        if not wrapped:
            lines.append(head)
        elif len(label) > label_room:
            lines.append(head)
            lines.extend(f"{padding}{line}" for line in wrapped)
        else:
            lines.append(f"{head.ljust(column)}{wrapped[0]}")
            lines.extend(f"{padding}{line}" for line in wrapped[1:])

    return "\n".join(lines)


__all__ = [
    "USAGE_PREFIX",
    "SproutHelpRenderer",
    "build_help_layout",
]
