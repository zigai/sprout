from __future__ import annotations

import pytest

from sprout.question import YES_NO_CHOICES, Question, parse_yes_no


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        (True, True),
        (False, False),
    ],
)
def test_should_ask_with_static_condition(condition: bool, expected: bool) -> None:
    question = Question(key="name", prompt="Project name", when=condition)

    assert question.should_ask({}) is expected


def test_should_ask_with_callable_condition() -> None:
    question = Question(
        key="license_reason",
        prompt="Why no license?",
        when=lambda answers: answers.get("use_license") is False,
    )

    assert question.should_ask({"use_license": False}) is True
    assert question.should_ask({"use_license": True}) is False


def test_should_ask_raises_type_error_for_non_bool_result() -> None:
    question = Question(
        key="license_reason",
        prompt="Why no license?",
        when=lambda _answers: "no",
    )

    with pytest.raises(TypeError, match="condition must return a bool"):
        question.should_ask({})


def test_should_ask_wraps_condition_errors() -> None:
    def failing_condition(_answers: dict[str, object]) -> bool:
        raise RuntimeError("boom")

    question = Question(
        key="license_reason",
        prompt="Why no license?",
        when=failing_condition,
    )

    with pytest.raises(ValueError, match="failed to evaluate condition: boom"):
        question.should_ask({})


def test_question_yes_no_builder_defaults_to_yes() -> None:
    question = Question.yes_no(key="git_init", prompt="Initialize git?")

    assert question.resolve_default({}) == "yes"
    assert question.resolve_choices({}) == list(YES_NO_CHOICES)
    assert question.parser is not None
    assert question.parser("yes", {}) is True
    assert question.parser("no", {}) is False


def test_question_yes_no_builder_supports_false_default() -> None:
    question = Question.yes_no(
        key="create_github_repo",
        prompt="Create GitHub repo?",
        default=False,
    )

    assert question.resolve_default({}) == "no"


def test_parse_yes_no_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="expected yes or no"):
        parse_yes_no("maybe", {})
