from __future__ import annotations

import pytest

from sprout.prompt.processing import AnswerProcessor, apply_parser, run_validator
from sprout.prompt.question import Question


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
