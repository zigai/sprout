from __future__ import annotations

import re
from collections.abc import Iterator
from io import StringIO

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output.vt100 import Vt100_Output
from rich.cells import cell_len
from rich.console import Console

from sprout.prompt.processing import ResolvedPrompt
from sprout.prompt.question import Question
from sprout.prompt.style import InlineStyle, MenuStyle, Style
from sprout.prompt.terminal import (
    DEFAULT_THEME,
    DefaultPlaceholderBindings,
    FallbackChoicePrompt,
    TerminalQuestion,
    as_choice_values,
    console,
    fallback_default_values,
    fallback_lookup_maps,
)


def test_fallback_default_values_and_choice_value_helpers() -> None:
    single = Question(key="license", prompt="License")
    multi = Question(key="workflows", prompt="Workflows", multiselect=True)

    assert fallback_default_values(single, "mit") == ["mit"]
    assert fallback_default_values(single, None) == []
    assert fallback_default_values(multi, ["tests", "lint"]) == ["tests", "lint"]
    assert as_choice_values("x") == ["x"]
    assert as_choice_values(("a", "b")) == ["a", "b"]


def test_fallback_lookup_maps_and_token_resolution() -> None:
    choices = [("tests", "Tests"), ("lint", "Lint")]
    value_map, label_map, index_map = fallback_lookup_maps(choices)

    assert (value_map, label_map, index_map) == (
        {"tests": "tests", "lint": "lint"},
        {"tests": "tests", "lint": "lint"},
        {"1": "tests", "2": "lint"},
    )

    prompt = FallbackChoicePrompt(
        question=Question(key="workflow", prompt="Workflow"),
        answers={},
        default_value=None,
        choices=choices,
    )

    assert prompt._resolve_token("1") == "tests"
    assert prompt._resolve_token("lint") == "lint"
    assert prompt._resolve_token("Tests") == "tests"
    assert prompt._resolve_token("unknown") is None


def test_resolve_fallback_choice_uses_default_and_reports_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question = Question(key="license", prompt="License")
    style = Style()
    errors: list[str] = []
    monkeypatch.setattr(
        "sprout.prompt.terminal.print_error", lambda message, _style: errors.append(str(message))
    )

    prompt = FallbackChoicePrompt(
        question=question,
        answers={},
        default_value="mit",
        choices=[("mit", "MIT")],
        style=style,
    )
    resolved = prompt.resolve_choice("")
    assert resolved == "mit"

    prompt_without_default = FallbackChoicePrompt(
        question=question,
        answers={},
        default_value=None,
        choices=[("mit", "MIT")],
        style=style,
    )
    unresolved = prompt_without_default.resolve_choice("")
    assert unresolved is None
    assert "Please choose a value." in errors


def test_default_placeholder_bindings_own_default_text() -> None:
    class FakeBuffer:
        def __init__(self) -> None:
            self.text = ""
            self.cursor_position = 0

        def insert_text(self, value: str) -> None:
            self.text = value
            self.cursor_position = len(value)

        def cursor_left(self, *, count: int) -> None:
            self.cursor_position -= count

        def cursor_right(self, *, count: int) -> None:
            self.cursor_position += count

        def delete_before_cursor(self, *, count: int) -> None:
            self.text = self.text[:-count]
            self.cursor_position = len(self.text)

        def delete(self, *, count: int) -> None:
            self.text = self.text[count:]

    buffer = FakeBuffer()
    bindings = DefaultPlaceholderBindings("demo")

    bindings._move_left(buffer)
    assert buffer.text == "demo"
    assert buffer.cursor_position == 3

    bindings._delete(buffer)
    assert buffer.text == "emo"


def test_fallback_choice_multiselect_retries_on_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: Iterator[str] = iter(["oops", "1,2"])
    errors: list[str] = []
    summaries: list[object] = []

    monkeypatch.setattr("sprout.prompt.terminal.console.input", lambda _prompt: next(responses))
    monkeypatch.setattr(
        "sprout.prompt.terminal.print_error", lambda message, _style: errors.append(str(message))
    )
    monkeypatch.setattr(
        "sprout.prompt.terminal.print_fallback_choices", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "sprout.prompt.terminal.print_choice_summary",
        lambda _question, value, _map, _style: summaries.append(value),
    )

    question = Question(key="workflows", prompt="Workflows", multiselect=True)
    result = FallbackChoicePrompt(
        question=question,
        answers={},
        default_value=[],
        choices=[("tests", "Tests"), ("lint", "Lint")],
        style=Style(),
    ).ask()

    assert result == ["tests", "lint"]
    assert any("Unknown choice" in error for error in errors)
    assert summaries
    assert summaries[-1] == ["tests", "lint"]


_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def _rendered_application_lines(output: str) -> list[str]:
    rendered = output[: output.rfind("\x1b[J")]
    return [line for line in _ANSI_ESCAPE.sub("", rendered).splitlines() if line]


def test_print_header_separates_and_indents_wrapped_help(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = StringIO()
    capture = Console(file=stream, force_terminal=False, width=32)
    monkeypatch.setattr("sprout.prompt.terminal.console", capture)
    question = Question(
        key="project",
        prompt="Choose a project",
        help="This help sentence is long enough to wrap across multiple lines.",
        choices=[("one", "First"), ("two", "Second")],
    )
    terminal = TerminalQuestion(
        question,
        ResolvedPrompt.from_question(question, {}),
        Style(),
    )

    terminal.print_header()

    lines = stream.getvalue().splitlines()
    assert lines[0].rstrip() == "? Choose a project"
    assert len(lines[1:]) > 1
    assert all(line.startswith("  ") for line in lines[1:])
    assert "First" not in stream.getvalue()
    assert "Enter select" not in stream.getvalue()


def test_inline_application_wraps_footer_and_erases_completed_body() -> None:
    question = Question(
        key="confirm",
        prompt="Confirm",
        choices=[("yes", "Yes"), ("no", "No")],
        default="yes",
    )
    style = Style(inline=InlineStyle(instruction="←/→ move  Enter select"))
    terminal = TerminalQuestion(
        question,
        ResolvedPrompt.from_question(question, {}),
        style,
    )
    stream = StringIO()
    output = Vt100_Output(
        stream,
        get_size=lambda: Size(rows=12, columns=40),
        term="xterm",
    )

    with create_pipe_input() as pipe:
        pipe.send_text("\x1b[C\r")
        with create_app_session(input=pipe, output=output):
            result = terminal.run_inline_application()

    raw = stream.getvalue()
    lines = _rendered_application_lines(raw)
    assert result == "no"
    assert lines == ["  ● Yes / ○ No", "  ←/→ move  Enter select"]
    assert raw.count(style.inline.instruction) == 1
    assert all(cell_len(line) <= 40 for line in lines)
    assert "\x1b[?1049h" not in raw
    assert raw.rfind("\x1b[J") > raw.rfind(style.inline.instruction)


@pytest.mark.parametrize(
    ("multiselect", "keys", "expected", "instruction"),
    [
        (False, "\x1b[B\r", "lint", "↑/↓ move  Enter select"),
        (
            True,
            " \x1b[B \r",
            ["tests", "lint"],
            "↑/↓ move  Space toggle  Enter confirm",
        ),
    ],
)
def test_vertical_application_wraps_footer_and_erases_completed_body(
    multiselect: bool,
    keys: str,
    expected: object,
    instruction: str,
) -> None:
    choices = [("tests", "Run tests"), ("lint", "Lint and format")]
    question = Question(
        key="tasks",
        prompt="Tasks",
        choices=choices,
        default=[] if multiselect else "tests",
        multiselect=multiselect,
    )
    style = Style(
        menu=MenuStyle(
            instruction_single="↑/↓ move  Enter select",
            instruction_multi="↑/↓ move  Space toggle  Enter confirm",
        )
    )
    terminal = TerminalQuestion(
        question,
        ResolvedPrompt.from_question(question, {}),
        style,
    )
    stream = StringIO()
    output = Vt100_Output(
        stream,
        get_size=lambda: Size(rows=12, columns=40),
        term="xterm",
    )

    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        with create_app_session(input=pipe, output=output):
            result = terminal.run_choice_application(choices, question.default)

    raw = stream.getvalue()
    lines = _rendered_application_lines(raw)
    assert result == expected
    assert lines[-1] == f"  {instruction}"
    body_index = next(idx for idx, line in enumerate(lines) if "Run tests" in line)
    assert body_index < lines.index(f"  {instruction}")
    assert raw.count(instruction) == 1
    assert all(cell_len(line) <= 40 for line in lines)
    assert "\x1b[?1049h" not in raw
    assert raw.rfind("\x1b[J") > raw.rfind(instruction)


def test_default_theme_configures_blue_link_and_path_styles() -> None:
    assert console.get_style("repr.path").color.name == "bright_blue"
    assert console.get_style("repr.filename").color.name == "bright_blue"
    assert console.get_style("repr.url").color.name == "bright_blue"
    assert console.get_style("repr.url").underline is True
    assert DEFAULT_THEME.styles["repr.path"].color.name == "bright_blue"
    assert DEFAULT_THEME.styles["repr.filename"].color.name == "bright_blue"
    assert DEFAULT_THEME.styles["markdown.link"].color.name == "bright_blue"
