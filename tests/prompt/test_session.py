from __future__ import annotations

from collections.abc import Iterator
from io import StringIO

import pytest
from rich.console import Console

from sprout.errors import SproutPromptError
from sprout.prompt.layout import Layout, Step, build_layout
from sprout.prompt.question import Question
from sprout.prompt.session import QuestionPrompt, collect_answers
from sprout.prompt.style import CompactStyle, RailStyle, Style
from sprout.prompt.terminal import TerminalQuestion


@pytest.mark.parametrize(
    ("use_license", "response", "expected_calls", "expected_answers"),
    [
        pytest.param(True, "asked", [], {"use_license": True}, id="condition-false"),
        pytest.param(
            False,
            "not needed",
            ["license_reason"],
            {"use_license": False, "license_reason": "not needed"},
            id="condition-true",
        ),
    ],
)
def test_collect_answers_respects_question_condition(
    monkeypatch: pytest.MonkeyPatch,
    use_license: bool,
    response: str,
    expected_calls: list[str],
    expected_answers: dict[str, object],
) -> None:
    calls: list[str] = []

    def fake_ask(prompt: QuestionPrompt) -> object:
        calls.append(prompt.question.key)
        return response

    monkeypatch.setattr(QuestionPrompt, "ask", fake_ask)

    questions = [
        Question(key="use_license", prompt="Use a license?"),
        Question(
            key="license_reason",
            prompt="Why no license?",
            when=lambda answers: answers.get("use_license") is False,
        ),
    ]

    answers = collect_answers(questions, initial_answers={"use_license": use_license})

    assert calls == expected_calls
    assert answers == expected_answers


def test_collect_answers_chained_conditions_with_skipped_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_ask(prompt: QuestionPrompt) -> object:
        calls.append(prompt.question.key)
        return "fallback"

    monkeypatch.setattr(QuestionPrompt, "ask", fake_ask)

    questions = [
        Question(key="feature_enabled", prompt="Enable feature?"),
        Question(
            key="feature_mode",
            prompt="Feature mode",
            when=lambda answers: answers.get("feature_enabled") is False,
        ),
        Question(
            key="fallback_mode",
            prompt="Fallback mode",
            when=lambda answers: "feature_mode" not in answers,
        ),
    ]

    answers = collect_answers(questions, initial_answers={"feature_enabled": True})

    assert calls == ["fallback_mode"]
    assert answers == {"feature_enabled": True, "fallback_mode": "fallback"}


def test_collect_answers_applies_cli_override_when_condition_would_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_ask(prompt: QuestionPrompt) -> object:
        raise AssertionError(f"unexpected prompt for {prompt.question.key}")

    monkeypatch.setattr(QuestionPrompt, "ask", fake_ask)

    def failing_condition(_answers: dict[str, object]) -> bool:
        raise RuntimeError("condition should not run")

    questions = [
        Question(key="use_license", prompt="Use a license?"),
        Question(
            key="license_reason",
            prompt="Why no license?",
            when=failing_condition,
            parser=lambda raw, _answers: raw.upper(),
        ),
    ]

    answers = collect_answers(
        questions,
        initial_answers={"use_license": True, "license_reason": "from-cli"},
    )

    assert answers == {"use_license": True, "license_reason": "FROM-CLI"}


def test_collect_answers_exits_when_condition_returns_non_bool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_ask(prompt: QuestionPrompt) -> object:
        raise AssertionError(f"unexpected prompt for {prompt.question.key}")

    monkeypatch.setattr(QuestionPrompt, "ask", fake_ask)

    questions = [
        Question(
            key="broken",
            prompt="Broken condition",
            when=lambda _answers: "yes",
        ),
    ]

    with pytest.raises(SproutPromptError, match="broken: condition must return a bool"):
        collect_answers(questions)


def _layout(question: Question, style: Style | None = None) -> Layout:
    return build_layout(style or CompactStyle(), [question])


def _record_answers(monkeypatch: pytest.MonkeyPatch, summaries: list[str]) -> None:
    monkeypatch.setattr(
        "sprout.prompt.session.print_answer",
        lambda _question, display, _layout: summaries.append(display),
    )


def test_prompt_for_text_accepts_empty_string_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[str] = []
    summaries: list[str] = []

    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: False)
    monkeypatch.setattr("sprout.prompt.terminal.console.input", lambda _prompt: "")
    monkeypatch.setattr(
        "sprout.prompt.session.print_error", lambda message, _layout: errors.append(str(message))
    )
    _record_answers(monkeypatch, summaries)

    question = Question(key="description", prompt="Description", default="")
    result = QuestionPrompt(question, {}, _layout(question)).ask()

    assert result == ""
    assert summaries == [""]
    assert errors == []


def test_prompt_for_text_noninteractive_retries_until_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: Iterator[str] = iter(["", "value"])
    errors: list[str] = []

    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: False)
    monkeypatch.setattr("sprout.prompt.terminal.console.input", lambda _prompt: next(responses))
    monkeypatch.setattr(
        "sprout.prompt.session.print_error", lambda message, _layout: errors.append(str(message))
    )
    _record_answers(monkeypatch, [])

    question = Question(key="name", prompt="Project name")
    result = QuestionPrompt(question, {}, _layout(question)).ask()

    assert result == "value"
    assert "Please provide a value." in errors


@pytest.mark.parametrize(
    ("responses", "expected"),
    [
        (["MIT"], "MIT"),
        (["mit"], "mit"),
        (["unknown", "1"], "MIT"),
    ],
    ids=["uppercase-value", "lowercase-value", "unknown-then-index"],
)
def test_fallback_single_choice_preserves_values_and_rejects_unknown(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[str],
    expected: str,
) -> None:
    inputs = iter(responses)
    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: False)
    monkeypatch.setattr("sprout.prompt.terminal.console.input", lambda _prompt: next(inputs))
    question = Question(
        key="license",
        prompt="License",
        choices=[("MIT", "Uppercase license"), ("mit", "Lowercase license")],
    )

    assert QuestionPrompt(question, {}, _layout(question)).ask() == expected


@pytest.mark.parametrize(
    ("multiselect", "default", "expected"),
    [(False, "public", "private"), (True, ["public"], ["private"])],
    ids=["single", "multiple"],
)
def test_fallback_choice_rejects_default_outside_choices(
    monkeypatch: pytest.MonkeyPatch,
    multiselect: bool,
    default: str | list[str],
    expected: str | list[str],
) -> None:
    inputs = iter(["", "1"])
    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: False)
    monkeypatch.setattr("sprout.prompt.terminal.console.input", lambda _prompt: next(inputs))
    question = Question(
        key="visibility",
        prompt="Visibility",
        default=default,
        choices=[("private", "Private")],
        multiselect=multiselect,
    )

    assert QuestionPrompt(question, {}, _layout(question)).ask() == expected


@pytest.mark.parametrize(
    ("responses", "expected"),
    [(["Preview"], "dry-run"), (["PREVIEW"], "publish"), (["preview", "1"], "dry-run")],
    ids=["first-label", "second-label", "ambiguous-label"],
)
def test_fallback_choice_preserves_label_identity(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[str],
    expected: str,
) -> None:
    inputs = iter(responses)
    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: False)
    monkeypatch.setattr("sprout.prompt.terminal.console.input", lambda _prompt: next(inputs))
    question = Question(
        key="action",
        prompt="Action",
        choices=[("dry-run", "Preview"), ("publish", "PREVIEW")],
    )

    assert QuestionPrompt(question, {}, _layout(question)).ask() == expected


def test_live_yes_no_question_parses_selection_and_prints_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summaries: list[str] = []
    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: True)
    monkeypatch.setattr(TerminalQuestion, "run_menu_application", lambda _terminal, _default: "no")
    _record_answers(monkeypatch, summaries)
    question = Question.yes_no(
        key="publish",
        prompt="Publish?",
        help_text="Requires credentials.",
    )

    result = QuestionPrompt(question, {}, _layout(question)).ask()

    assert result is False
    assert summaries == ["No"]


def test_choice_validation_shows_error_in_prompt_without_committing_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selections = iter(["yes", "no"])
    shown: list[tuple[object, str | None]] = []
    summaries: list[str] = []
    answers = {"description": ""}

    def fake_menu(terminal: TerminalQuestion, default: object) -> object:
        shown.append((default, terminal.view.error))
        return next(selections)

    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: True)
    monkeypatch.setattr(TerminalQuestion, "run_menu_application", fake_menu)
    _record_answers(monkeypatch, summaries)
    question = Question.yes_no(
        key="publish",
        prompt="Publish?",
        validators=[
            lambda _raw, candidate: (
                not candidate["publish"] or bool(candidate["description"]),
                "A description is required.",
            )
        ],
    )

    assert QuestionPrompt(question, answers, _layout(question)).ask() is False
    assert shown == [("yes", None), ("yes", "A description is required.")]
    assert summaries == ["No"]
    assert answers == {"description": ""}


@pytest.mark.parametrize(
    ("width", "expected_kind"),
    [(19, "confirm"), (18, "select")],
)
def test_two_choices_render_inline_only_when_row_fits(
    monkeypatch: pytest.MonkeyPatch,
    width: int,
    expected_kind: str,
) -> None:
    monkeypatch.setattr(
        "sprout.prompt.session.console",
        Console(file=StringIO(), force_terminal=False, width=width),
    )
    question = Question(
        key="kind",
        prompt="Kind",
        choices=[("alpha", "Alpha"), ("beta", "Beta")],
        default="alpha",
    )

    assert QuestionPrompt(question, {}, _layout(question)).view.kind == expected_kind


def test_live_text_prompt_prints_typed_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    summaries: list[str] = []
    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: True)
    monkeypatch.setattr(
        TerminalQuestion, "run_text_application", lambda _terminal, _initial: "typed response"
    )
    _record_answers(monkeypatch, summaries)
    question = Question(key="description", prompt="Description")

    result = QuestionPrompt(question, {}, _layout(question)).ask()

    assert result == "typed response"
    assert summaries == ["typed response"]


def test_live_text_validation_error_keeps_typed_text(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(["Bad", "good"])
    shown: list[tuple[str, str | None]] = []

    def fake_text(terminal: TerminalQuestion, initial: str) -> str:
        shown.append((initial, terminal.view.error))
        return next(responses)

    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: True)
    monkeypatch.setattr(TerminalQuestion, "run_text_application", fake_text)
    _record_answers(monkeypatch, [])
    question = Question(
        key="name",
        prompt="Name",
        validators=[lambda raw: (raw.islower(), "Use lowercase.")],
    )

    assert QuestionPrompt(question, {}, _layout(question)).ask() == "good"
    assert shown == [("", None), ("Bad", "Use lowercase.")]


def test_collect_answers_counts_steps_for_questions_left_to_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps: list[tuple[str, Step | None]] = []

    def fake_ask(prompt: QuestionPrompt) -> object:
        steps.append((prompt.question.key, prompt.view.step))
        return "value"

    monkeypatch.setattr(QuestionPrompt, "ask", fake_ask)
    questions = [
        Question(key="first", prompt="First"),
        Question(key="given", prompt="Given"),
        Question(key="maybe", prompt="Maybe", when=lambda answers: "first" in answers),
        Question(key="never", prompt="Never", when=False),
        Question(key="last", prompt="Last"),
    ]

    collect_answers(questions, initial_answers={"given": "cli"})

    assert steps == [("first", Step(1, 3)), ("maybe", Step(2, 3)), ("last", Step(3, 3))]


@pytest.mark.parametrize(
    ("initial_answers", "title", "expected_lines"),
    [
        ({"name": "cli"}, None, []),
        ({"name": "cli"}, "Make a demo", ["┌   sprout   Make a demo", "│", "└"]),
        ({}, None, ["┌   sprout", "│", "└"]),
    ],
    ids=["nothing-asked", "title-only", "asked"],
)
def test_rail_frame_wraps_title_and_asked_questions(
    monkeypatch: pytest.MonkeyPatch,
    initial_answers: dict[str, object],
    title: str | None,
    expected_lines: list[str],
) -> None:
    stream = StringIO()
    monkeypatch.setattr(
        "sprout.prompt.terminal.console", Console(file=stream, force_terminal=False, width=40)
    )
    monkeypatch.setattr(QuestionPrompt, "ask", lambda _prompt: "value")

    collect_answers(
        [Question(key="name", prompt="Name")],
        style=RailStyle(),
        initial_answers=initial_answers,
        title=title,
    )

    assert [line.rstrip() for line in stream.getvalue().splitlines()] == expected_lines
