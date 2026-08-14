from __future__ import annotations

import sys
from collections.abc import Sequence

from interfacy.argparse_backend.argument_parser import namespace_to_dict

from sprout.cli.commands import dispatch_command, list_templates
from sprout.cli.parser import (
    CliInvocation,
    build_cli_parser,
    prepare_template_for_cli,
    registered_templates_for_new_help,
)
from sprout.errors import SproutError


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the CLI entrypoint and return an exit status code.

    Args:
        argv (Sequence[str] | None): Optional argument vector. If None, use `sys.argv[1:]`.

    Raises:
        SystemExit: If argument parsing or template execution fails.
    """
    try:
        return _run(argv)
    except SproutError as error:
        raise SystemExit(error.message) from error


def _run(argv: Sequence[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else None
    inspect_args = args_list if args_list is not None else sys.argv[1:]
    invocation = CliInvocation.from_args(inspect_args)
    trusted_templates = registered_templates_for_new_help(inspect_args, invocation)
    prepared = None
    try:
        prepared, help_note = prepare_template_for_cli(invocation)
        parser = build_cli_parser(
            prepared,
            help_note=help_note,
            trusted_templates=trusted_templates,
        )
        parsed = parser.parse_args(args_list)
        namespace = namespace_to_dict(parsed)
        command = namespace.get("command")
        if not isinstance(command, str):
            raise SystemExit("a command is required.")

        command_values = namespace.get(command)
        if command == "list" and command_values is None:
            return list_templates()
        if not isinstance(command_values, dict):
            raise SystemExit(f"failed to parse {command} command arguments.")

        merged_values = dict(command_values)
        merged_values.update(
            (key, value) for key, value in namespace.items() if key not in {"command", command}
        )

        return dispatch_command(command, merged_values, prepared)
    finally:
        if prepared is not None:
            prepared.close()


__all__ = ["main"]
