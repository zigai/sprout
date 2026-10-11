from __future__ import annotations

from collections.abc import Iterator
from io import StringIO

import pytest
from rich.console import Console

from sprout.errors import SproutPromptError
from sprout.prompt.processing import ResolvedPrompt
from sprout.prompt.question import Question
from sprout.prompt.session import QuestionPrompt, collect_answers
from sprout.prompt.style import InlineStyle, Style
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

    def fake_ask_question(question: Question, answers: dict[str, object], style: object) -> object:
        calls.append(question.key)
        return response

    monkeypatch.setattr("sprout.prompt.session.ask_question", fake_ask_question)

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

    def fake_ask_question(question: Question, answers: dict[str, object], style: object) -> object:
        calls.append(question.key)
        return "fallback"

    monkeypatch.setattr("sprout.prompt.session.ask_question", fake_ask_question)

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
    def fake_ask_question(question: Question, answers: dict[str, object], style: object) -> object:
        raise AssertionError(f"unexpected prompt for {question.key}")

    monkeypatch.setattr("sprout.prompt.session.ask_question", fake_ask_question)

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
    def fake_ask_question(question: Question, answers: dict[str, object], style: object) -> object:
        raise AssertionError(f"unexpected prompt for {question.key}")

    monkeypatch.setattr("sprout.prompt.session.ask_question", fake_ask_question)

    questions = [
        Question(
            key="broken",
            prompt="Broken condition",
            when=lambda _answers: "yes",
        ),
    ]

    with pytest.raises(SproutPromptError, match="broken: condition must return a bool"):
        collect_answers(questions)


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
    monkeypatch.setattr("sprout.prompt.terminal.supports_live_interaction", lambda: False)
    monkeypatch.setattr("sprout.prompt.terminal.console.input", lambda _prompt: next(inputs))
    question = Question(
        key="license",
        prompt="License",
        choices=[("MIT", "Uppercase license"), ("mit", "Lowercase license")],
    )

    assert QuestionPrompt(question, {}, Style()).ask() == expected


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

    assert QuestionPrompt(question, {}, Style()).ask() == expected


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

    assert QuestionPrompt(question, {}, Style()).ask() == expected


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


@pytest.mark.parametrize("inline", [True, False])
def test_choice_validation_retries_without_committing_rejected_answer(
    monkeypatch: pytest.MonkeyPatch,
    inline: bool,
) -> None:
    selections = iter(["yes", "no"])
    errors: list[str] = []
    summaries: list[object] = []
    answers = {"description": ""}
    monkeypatch.setattr("sprout.prompt.session.supports_live_interaction", lambda: True)
    monkeypatch.setattr(TerminalQuestion, "should_use_inline", lambda _terminal: inline)
    monkeypatch.setattr(
        TerminalQuestion, "run_inline_application", lambda _terminal: next(selections)
    )
    monkeypatch.setattr(
        TerminalQuestion,
        "run_choice_application",
        lambda _terminal, _choices, _default: next(selections),
    )
    monkeypatch.setattr(
        "sprout.prompt.session.print_error", lambda error, _style: errors.append(str(error))
    )
    monkeypatch.setattr(
        "sprout.prompt.session.print_choice_summary",
        lambda _question, value, _labels, _style: summaries.append(value),
    )
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

    assert QuestionPrompt(question, answers, Style()).ask() is False
    assert errors == ["A description is required."]
    assert summaries == ["no"]
    assert answers == {"description": ""}


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
