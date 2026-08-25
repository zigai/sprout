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

from sprout.prompt.processing import AnswerProcessor, ResolvedPrompt, apply_parser, run_validator
from sprout.prompt.question import Question
from sprout.prompt.session import QuestionPrompt
from sprout.prompt.style import InlineStyle, MenuStyle, Style
from sprout.prompt.terminal import (
    DefaultPlaceholderBindings,
    FallbackChoicePrompt,
    TerminalQuestion,
    as_choice_values,
    fallback_default_values,
    fallback_lookup_maps,
)


def test_apply_parser_uses_parser_for_single_values() -> None:
    question = Question(
        key="name",
        prompt="Name",
        parser=lambda raw, _answers: raw.upper(),
    )

    assert apply_parser(question, "sprout", {}) == "SPROUT"


def test_apply_parser_skips_multiselect_parser() -> None:
    question = Question(
        key="tags",
        prompt="Tags",
        multiselect=True,
        parser=lambda raw, _answers: raw.upper(),
    )

    assert apply_parser(question, ["a"], {}) == ["a"]


def test_run_validator_supports_both_signatures() -> None:
    question = Question(
        key="name",
        prompt="Name",
        validators=[
            lambda raw, answers: (raw == "ok" and answers["name"] == "ok", "bad"),
            lambda raw: (raw == "ok", "bad"),
        ],
    )

    run_validator(question, "ok", {}, raw="ok")


def test_run_validator_raises_value_error() -> None:
    question = Question(
        key="name",
        prompt="Name",
        validators=[lambda _raw, _answers: (False, "invalid input")],
    )

    with pytest.raises(ValueError, match="invalid input"):
        run_validator(question, "bad", {}, raw="bad")


def test_run_validator_preserves_validator_type_error() -> None:
    def broken_validator(_raw: str, _answers: dict[str, object]) -> tuple[bool, str | None]:
        raise TypeError("validator bug")

    question = Question(
        key="name",
        prompt="Name",
        validators=[broken_validator],
    )

    with pytest.raises(TypeError, match="validator bug"):
        run_validator(question, "bad", {}, raw="bad")


def test_apply_cli_answer_validates_single_choices() -> None:
    question = Question(
        key="license",
        prompt="License",
        choices=[("mit", "MIT"), ("apache", "Apache")],
    )

    assert AnswerProcessor(question, {}).process_cli("mit") == "mit"

    with pytest.raises(ValueError, match="invalid choice"):
        AnswerProcessor(question, {}).process_cli("bsd")


def test_apply_cli_answer_validates_multiselect_choices() -> None:
    question = Question(
        key="workflows",
        prompt="Workflows",
        multiselect=True,
        choices=[("tests", "Tests"), ("lint", "Lint")],
        parser=lambda _raw, _answers: (_ for _ in ()).throw(AssertionError("parser not expected")),
    )

    assert AnswerProcessor(question, {}).process_cli(["tests", "lint"]) == ["tests", "lint"]

    with pytest.raises(ValueError, match="invalid choice\\(s\\)"):
        AnswerProcessor(question, {}).process_cli(["tests", "deploy"])


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


def test_prompt_for_text_accepts_empty_string_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[str] = []
    summaries: list[str] = []

    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: False)
    monkeypatch.setattr("sprout.prompt.terminal.supports_live_interaction", lambda: False)
    monkeypatch.setattr("sprout.prompt.terminal.console.input", lambda _prompt: "")
    monkeypatch.setattr(
        "sprout.prompt.session.print_error", lambda message, _style: errors.append(str(message))
    )
    monkeypatch.setattr(
        "sprout.prompt.session.print_text_summary", lambda value, _style: summaries.append(value)
    )

    question = Question(key="description", prompt="Description", default="")
    result = QuestionPrompt(question, {}, Style()).ask()

    assert result == ""
    assert summaries == [""]
    assert errors == []


def test_prompt_for_text_noninteractive_retries_until_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: Iterator[str] = iter(["", "value"])
    errors: list[str] = []

    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: False)
    monkeypatch.setattr("sprout.prompt.terminal.supports_live_interaction", lambda: False)
    monkeypatch.setattr("sprout.prompt.terminal.console.input", lambda _prompt: next(responses))
    monkeypatch.setattr(
        "sprout.prompt.session.print_error", lambda message, _style: errors.append(str(message))
    )
    monkeypatch.setattr("sprout.prompt.session.print_text_summary", lambda _value, _style: None)

    question = Question(key="name", prompt="Project name")
    result = QuestionPrompt(question, {}, Style()).ask()

    assert result == "value"
    assert "Please provide a value." in errors


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


def test_question_prompt_shows_header_for_live_inline_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    summaries: list[object] = []
    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: True)
    monkeypatch.setattr(
        TerminalQuestion,
        "print_header",
        lambda _terminal: events.append("header"),
    )
    monkeypatch.setattr(TerminalQuestion, "should_use_inline", lambda _terminal: True)
    monkeypatch.setattr(
        TerminalQuestion,
        "run_inline_application",
        lambda _terminal: events.append("inline") or "no",
    )
    monkeypatch.setattr(
        "sprout.prompt.session.print_choice_summary",
        lambda _question, value, labels, _style: summaries.append((value, labels[value])),
    )
    question = Question.yes_no(
        key="publish",
        prompt="Publish?",
        help_text="Requires credentials.",
    )

    result = QuestionPrompt(question, {}, Style()).ask()

    assert result is False
    assert events == ["header", "inline"]
    assert summaries == [("no", "No")]


@pytest.mark.parametrize(
    ("width", "expected_branch"),
    [(20, "inline"), (19, "menu")],
)
def test_question_prompt_selects_inline_only_when_choice_row_fits(
    monkeypatch: pytest.MonkeyPatch,
    width: int,
    expected_branch: str,
) -> None:
    stream = StringIO()
    monkeypatch.setattr(
        "sprout.prompt.terminal.console",
        Console(file=stream, force_terminal=False, width=width),
    )
    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: True)
    monkeypatch.setattr(TerminalQuestion, "print_header", lambda _terminal: None)
    calls: list[object] = []
    monkeypatch.setattr(
        TerminalQuestion,
        "run_inline_application",
        lambda _terminal: calls.append("inline") or "alpha",
    )

    def fake_menu(
        _terminal: TerminalQuestion,
        choices: object,
        default: object,
    ) -> str:
        calls.append(("menu", list(choices), default))
        return "alpha"

    monkeypatch.setattr(TerminalQuestion, "run_choice_application", fake_menu)
    monkeypatch.setattr(
        "sprout.prompt.session.print_choice_summary",
        lambda *_args: None,
    )
    style = Style(
        inline=InlineStyle(
            selected_icon="◆",
            unselected_icon="◇",
            separator=" <-> ",
        )
    )
    choices = [("alpha", "Alpha"), ("beta", "Beta")]
    question = Question(
        key="kind",
        prompt="Kind",
        choices=choices,
        default="alpha",
    )
    terminal = TerminalQuestion(
        question,
        ResolvedPrompt.from_question(question, {}),
        style,
    )

    assert terminal.should_use_inline() is (expected_branch == "inline")
    result = QuestionPrompt(question, {}, style).ask()

    assert result == "alpha"

    if expected_branch == "inline":
        assert calls == ["inline"]
    else:
        assert calls == [("menu", choices, "alpha")]


def test_live_text_prompt_erases_input_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summaries: list[str] = []
    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: True)
    monkeypatch.setattr(TerminalQuestion, "print_header", lambda _terminal: None)
    monkeypatch.setattr(
        TerminalQuestion,
        "read_text_response",
        lambda _terminal, _default: "typed response",
    )
    monkeypatch.setattr(
        "sprout.prompt.session.print_text_summary",
        lambda value, _style: summaries.append(value),
    )
    question = Question(key="description", prompt="Description")

    result = QuestionPrompt(question, {}, Style()).ask()

    assert result == "typed response"
    assert summaries == ["typed response"]
    from sprout.prompt import session

    assert not hasattr(session, "highlight_prompt_line")


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
