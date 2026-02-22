from __future__ import annotations

import pytest

from sprout.prompt import collect_answers
from sprout.question import Question


def test_collect_answers_skips_question_when_condition_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_ask_question(question: Question, answers: dict[str, object], style: object) -> object:
        calls.append(question.key)
        return "asked"

    monkeypatch.setattr("sprout.prompt.ask_question", fake_ask_question)

    questions = [
        Question(key="use_license", prompt="Use a license?"),
        Question(
            key="license_reason",
            prompt="Why no license?",
            when=lambda answers: answers.get("use_license") is False,
        ),
    ]

    answers = collect_answers(questions, initial_answers={"use_license": True})

    assert calls == []
    assert answers == {"use_license": True}


def test_collect_answers_prompts_when_condition_true(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_ask_question(question: Question, answers: dict[str, object], style: object) -> object:
        calls.append(question.key)
        return "not needed"

    monkeypatch.setattr("sprout.prompt.ask_question", fake_ask_question)

    questions = [
        Question(key="use_license", prompt="Use a license?"),
        Question(
            key="license_reason",
            prompt="Why no license?",
            when=lambda answers: answers.get("use_license") is False,
        ),
    ]

    answers = collect_answers(questions, initial_answers={"use_license": False})

    assert calls == ["license_reason"]
    assert answers == {"use_license": False, "license_reason": "not needed"}


def test_collect_answers_chained_conditions_with_skipped_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_ask_question(question: Question, answers: dict[str, object], style: object) -> object:
        calls.append(question.key)
        return "fallback"

    monkeypatch.setattr("sprout.prompt.ask_question", fake_ask_question)

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

    monkeypatch.setattr("sprout.prompt.ask_question", fake_ask_question)

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

    monkeypatch.setattr("sprout.prompt.ask_question", fake_ask_question)

    questions = [
        Question(
            key="broken",
            prompt="Broken condition",
            when=lambda _answers: "yes",
        ),
    ]

    with pytest.raises(SystemExit, match="broken: condition must return a bool"):
        collect_answers(questions)
