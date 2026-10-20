from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from io import StringIO
from typing import Any

import pytest
from prompt_toolkit.application import Application, create_app_session
from prompt_toolkit.data_structures import Point, Size
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output.vt100 import Vt100_Output
from rich.cells import cell_len
from rich.console import Console

from sprout.prompt.layout import Layout, PromptView, build_layout
from sprout.prompt.question import Question
from sprout.prompt.style import CompactStyle, Hints, RailStyle, Style
from sprout.prompt.terminal import (
    DEFAULT_THEME,
    DefaultPlaceholderBindings,
    FallbackChoicePrompt,
    TerminalQuestion,
    as_choice_values,
    console,
    fallback_default_values,
    fallback_lookup_maps,
    prompt_toolkit_style_string,
)

STYLES = [pytest.param(CompactStyle(), id="compact"), pytest.param(RailStyle(), id="rail")]


def _layout(question: Question, style: Style | None = None) -> Layout:
    return build_layout(style or CompactStyle(), [question])


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

    question = Question(key="workflow", prompt="Workflow")
    prompt = FallbackChoicePrompt(
        question=question,
        answers={},
        default_value=None,
        choices=choices,
        layout=_layout(question),
    )

    assert prompt._resolve_token("1") == "tests"
    assert prompt._resolve_token("lint") == "lint"
    assert prompt._resolve_token("Tests") == "tests"
    assert prompt._resolve_token("unknown") is None


def test_resolve_fallback_choice_uses_default_and_reports_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question = Question(key="license", prompt="License")
    errors: list[str] = []
    monkeypatch.setattr(
        "sprout.prompt.terminal.print_error", lambda message, _layout: errors.append(str(message))
    )

    prompt = FallbackChoicePrompt(
        question=question,
        answers={},
        default_value="mit",
        choices=[("mit", "MIT")],
        layout=_layout(question),
    )
    resolved = prompt.resolve_choice("")
    assert resolved == "mit"

    prompt_without_default = FallbackChoicePrompt(
        question=question,
        answers={},
        default_value=None,
        choices=[("mit", "MIT")],
        layout=_layout(question),
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
    summaries: list[str] = []

    monkeypatch.setattr("sprout.prompt.terminal.console.input", lambda _prompt: next(responses))
    monkeypatch.setattr(
        "sprout.prompt.terminal.print_error", lambda message, _layout: errors.append(str(message))
    )
    monkeypatch.setattr(
        "sprout.prompt.terminal.print_fallback_choices", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "sprout.prompt.terminal.print_answer",
        lambda _question, display, _layout: summaries.append(display),
    )

    question = Question(key="workflows", prompt="Workflows", multiselect=True)
    result = FallbackChoicePrompt(
        question=question,
        answers={},
        default_value=[],
        choices=[("tests", "Tests"), ("lint", "Lint")],
        layout=_layout(question),
    ).ask()

    assert result == ["tests", "lint"]
    assert any("Unknown choice" in error for error in errors)
    assert summaries == ["Tests, Lint"]


@pytest.mark.parametrize(
    ("rich_style", "expected"),
    [
        ("bright_cyan", "ansibrightcyan"),
        ("white", "ansigray"),
        ("bold black on bright_cyan", "bold ansiblack bg:ansibrightcyan"),
        ("dim italic #22d3ee", "dim italic #22d3ee"),
        ("color(196)", "#ff0000"),
        ("default on default", ""),
        ("", ""),
    ],
)
def test_prompt_toolkit_style_string_keeps_named_colors_and_attributes(
    rich_style: str,
    expected: str,
) -> None:
    assert prompt_toolkit_style_string(rich_style) == expected


_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def _first_frame(output: str) -> list[str]:
    # Later renders are partial diffs whose timing depends on how the platform delivers piped keys.
    start = output.index("\x1b[J")
    rendered = output[start : output.index("\x1b[?7h", start)]
    frames = _ANSI_ESCAPE.sub("\x00", rendered)
    return [line.replace("\x00", "") for line in frames.splitlines() if line.strip("\x00 ")]


def _run_application(keys: str, run: Callable[[], object], *, rows: int = 20) -> tuple[object, str]:
    stream = StringIO()
    output = Vt100_Output(stream, get_size=lambda: Size(rows=rows, columns=40), term="xterm")
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        with create_app_session(input=pipe, output=output):
            result = run()

    return result, stream.getvalue()


@pytest.mark.parametrize("style", STYLES)
def test_print_header_indents_wrapped_help(monkeypatch: pytest.MonkeyPatch, style: Style) -> None:
    stream = StringIO()
    monkeypatch.setattr(
        "sprout.prompt.terminal.console", Console(file=stream, force_terminal=False, width=32)
    )
    question = Question(
        key="project",
        prompt="Choose a project",
        help="This help sentence is long enough to wrap across multiple lines.",
        choices=[("one", "First"), ("two", "Second")],
    )
    view = PromptView(
        question=question, kind="select", choices=list(question.resolve_choices({}) or [])
    )

    TerminalQuestion(view, build_layout(style, [question])).print_header()

    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    title_index = next(idx for idx, line in enumerate(lines) if "Choose a project" in line)
    help_lines = lines[title_index + 1 :]
    prefix = help_lines[0][: help_lines[0].index("This")]
    assert len(help_lines) > 1
    assert all(line.startswith(prefix) and len(line) > len(prefix) for line in help_lines)
    assert all(cell_len(line) <= 32 for line in lines)
    assert "First" not in stream.getvalue()


@pytest.mark.parametrize("style", STYLES)
def test_confirm_application_moves_selection_and_erases_when_done(style: Style) -> None:
    question = Question(
        key="confirm",
        prompt="Confirm",
        choices=[("yes", "Yes"), ("no", "No")],
        default="yes",
    )
    view = PromptView(
        question=question, kind="confirm", choices=list(question.resolve_choices({}) or [])
    )
    terminal = TerminalQuestion(view, build_layout(style, [question]))

    result, raw = _run_application("\x1b[C\r", lambda: terminal.run_menu_application("yes"))

    lines = _first_frame(raw)
    assert result == "no"
    assert any("Confirm" in line for line in lines)
    assert any("Yes" in line and "No" in line for line in lines)
    assert lines[-1].rstrip().endswith("confirm")
    assert "\x1b[?1049h" not in raw
    assert raw.rfind("\x1b[J") > raw.rfind("confirm")


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize(
    ("multiselect", "keys", "expected"),
    [(False, "\x1b[B\r", "lint"), (True, " \x1b[B \r", ["tests", "lint"])],
    ids=["single", "multiple"],
)
def test_menu_application_returns_selection_with_hints_last(
    style: Style,
    multiselect: bool,
    keys: str,
    expected: object,
) -> None:
    question = Question(
        key="tasks",
        prompt="Tasks",
        choices=[("tests", "Run tests"), ("lint", "Lint and format")],
        multiselect=multiselect,
    )
    view = PromptView(
        question=question,
        kind="multiselect" if multiselect else "select",
        choices=list(question.resolve_choices({}) or []),
    )
    terminal = TerminalQuestion(view, build_layout(style, [question]))

    result, raw = _run_application(
        keys, lambda: terminal.run_menu_application([] if multiselect else "tests")
    )

    lines = _first_frame(raw)
    assert result == expected
    body_index = next(idx for idx, line in enumerate(lines) if "Run tests" in line)
    assert body_index < len(lines) - 1
    assert lines[-1].rstrip().endswith("confirm" if multiselect else "select")
    assert all(cell_len(line) <= 40 for line in lines)
    assert "\x1b[?1049h" not in raw


def test_multiselect_application_toggles_all_with_ctrl_a() -> None:
    question = Question(
        key="tasks",
        prompt="Tasks",
        choices=[("tests", "Tests"), ("lint", "Lint")],
        multiselect=True,
    )
    view = PromptView(
        question=question, kind="multiselect", choices=list(question.resolve_choices({}) or [])
    )
    terminal = TerminalQuestion(view, _layout(question))

    result, _raw = _run_application("\x01\r", lambda: terminal.run_menu_application(["lint"]))

    assert result == ["tests", "lint"]


LICENSES = [
    ("mit", "MIT License"),
    ("apache", "Apache License 2.0"),
    ("gpl3", "GNU General Public License v3.0"),
    ("gpl2", "GNU General Public License v2.0"),
    ("lgpl", "GNU Lesser General Public License"),
]


def _list_terminal(
    *, multiselect: bool, choices: list[tuple[str, str]] = LICENSES
) -> TerminalQuestion:
    question = Question(key="license", prompt="License", choices=choices, multiselect=multiselect)
    view = PromptView(
        question=question,
        kind="multiselect" if multiselect else "select",
        choices=list(choices),
    )
    return TerminalQuestion(view, _layout(question))


@pytest.mark.parametrize(
    ("keys", "expected"),
    [("gnu v2\r", "gpl2"), ("zzz\r\x15\r", "mit"), ("lesser\x15\r", "lgpl")],
    ids=["words-match", "enter-ignored-without-match", "clear-keeps-cursor"],
)
def test_select_application_filters_by_typed_search(keys: str, expected: str) -> None:
    terminal = _list_terminal(multiselect=False)

    result, _raw = _run_application(keys, lambda: terminal.run_menu_application("mit"))

    assert result == expected


def test_multiselect_search_keeps_space_for_toggle_and_ctrl_a_selects_matches() -> None:
    terminal = _list_terminal(multiselect=True)

    result, _raw = _run_application("mit \x15gnu\x01\r", lambda: terminal.run_menu_application([]))

    assert result == ["mit", "gpl3", "gpl2", "lgpl"]


def test_long_list_scrolls_with_more_markers() -> None:
    choices = [(f"item{index}", f"Item {index}") for index in range(12)]
    terminal = _list_terminal(multiselect=False, choices=choices)

    result, raw = _run_application("\x1b[6~\r", lambda: terminal.run_menu_application("item0"))

    frames = _ANSI_ESCAPE.sub("", raw)
    assert result == "item8"
    assert "↓ 4 more" in frames
    assert "Type to search" in frames
    assert "Item 11" not in frames


def test_search_cursor_follows_typed_query(monkeypatch: pytest.MonkeyPatch) -> None:
    choices = [(f"item{index}", f"Item {index}") for index in range(12)]
    terminal = _list_terminal(multiselect=False, choices=choices)
    cursors: list[Point] = []

    with create_pipe_input() as pipe:

        class RecordingApplication(Application[object]):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(after_render=self._record, **kwargs)

            def _record(self, app: Application[object]) -> None:
                screen = app.renderer._last_screen
                if screen is None:
                    return

                cursors.append(screen.get_cursor_position(app.layout.current_window))
                pipe.send_text("i" if len(cursors) == 1 else "\r")

        monkeypatch.setattr("sprout.prompt.terminal.Application", RecordingApplication)
        output = Vt100_Output(StringIO(), get_size=lambda: Size(rows=20, columns=40), term="xterm")
        with create_app_session(input=pipe, output=output):
            terminal.run_menu_application("item0")

    search_column = len("     / ")
    assert cursors[0] == Point(x=search_column, y=2)
    assert cursors[1] == Point(x=search_column + 1, y=2)


@pytest.mark.parametrize("style", STYLES)
def test_long_list_shrinks_to_fit_short_terminal_with_wrapped_help(style: Style) -> None:
    choices = [(f"item{index}", f"Item {index}") for index in range(12)]
    question = Question(
        key="item",
        prompt="Item",
        help="This help sentence is long enough to wrap across several lines here.",
        choices=choices,
    )
    view = PromptView(question=question, kind="select", choices=choices)
    terminal = TerminalQuestion(view, build_layout(style, [question]))

    result, raw = _run_application("\r", lambda: terminal.run_menu_application("item0"), rows=10)

    lines = _first_frame(raw)
    assert result == "item0"
    assert len(lines) <= 9
    assert any("more" in line for line in lines)
    assert any("Item 0" in line for line in lines)


@pytest.mark.parametrize(
    ("keys", "expected"),
    [("\t\r", "demo"), ("\t-app\r", "demo-app"), ("typed\r", "typed"), ("\r", "")],
    ids=["tab-default", "tab-then-edit", "typed", "empty"],
)
def test_text_application_fills_default_only_on_request(keys: str, expected: str) -> None:
    question = Question(key="name", prompt="Name", default="demo")
    view = PromptView(question=question, kind="text", choices=[], placeholder="demo")
    terminal = TerminalQuestion(view, _layout(question))

    result, _raw = _run_application(keys, terminal.run_text_application)

    assert result == expected


@pytest.mark.parametrize("style", STYLES)
def test_text_application_shows_error_and_keeps_typed_text(style: Style) -> None:
    question = Question(key="name", prompt="Name")
    view = PromptView(question=question, kind="text", choices=[], error="Use lowercase.")
    terminal = TerminalQuestion(view, build_layout(style, [question]))

    result, raw = _run_application("\r", lambda: terminal.run_text_application("Bad"))

    assert result == "Bad"
    assert any("Use lowercase." in line for line in _first_frame(raw))


def test_hidden_hints_leave_no_hint_line() -> None:
    question = Question(key="tasks", prompt="Tasks", choices=[("a", "A"), ("b", "B"), ("c", "C")])
    view = PromptView(
        question=question, kind="select", choices=list(question.resolve_choices({}) or [])
    )
    style = CompactStyle(hints=Hints(show=False))
    terminal = TerminalQuestion(view, build_layout(style, [question]))

    _result, raw = _run_application("\r", lambda: terminal.run_menu_application("a"))

    assert "select" not in raw


def test_default_theme_configures_blue_link_and_path_styles() -> None:
    assert console.get_style("repr.path").color.name == "bright_blue"
    assert console.get_style("repr.filename").color.name == "bright_blue"
    assert console.get_style("repr.url").color.name == "bright_blue"
    assert console.get_style("repr.url").underline is True
    assert DEFAULT_THEME.styles["repr.path"].color.name == "bright_blue"
    assert DEFAULT_THEME.styles["repr.filename"].color.name == "bright_blue"
    assert DEFAULT_THEME.styles["markdown.link"].color.name == "bright_blue"
