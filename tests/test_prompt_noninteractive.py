from __future__ import annotations

from collections.abc import Iterator

import pytest

from sprout.prompt import (
    _apply_cli_answer,
    _apply_parser,
    _as_choice_values,
    _fallback_choice,
    _fallback_default_values,
    _fallback_lookup_maps,
    _prompt_for_text,
    _resolve_fallback_choice,
    _resolve_fallback_token,
    _run_validator,
)
from sprout.question import Question
from sprout.style import Style


def test_apply_parser_uses_parser_for_single_values() -> None:
    question = Question(
        key="name",
        prompt="Name",
        parser=lambda raw, _answers: raw.upper(),
    )

    assert _apply_parser(question, "sprout", {}) == "SPROUT"


def test_apply_parser_skips_multiselect_parser() -> None:
    question = Question(
        key="tags",
        prompt="Tags",
        multiselect=True,
        parser=lambda raw, _answers: raw.upper(),
    )

    assert _apply_parser(question, ["a"], {}) == ["a"]


def test_run_validator_supports_both_signatures() -> None:
    question = Question(
        key="name",
        prompt="Name",
        validators=[
            lambda raw, answers: (raw == "ok" and answers["name"] == "ok", "bad"),
            lambda raw: (raw == "ok", "bad"),
        ],
    )

    _run_validator(question, "ok", {}, raw="ok")


def test_run_validator_raises_value_error() -> None:
    question = Question(
        key="name",
        prompt="Name",
        validators=[lambda _raw, _answers: (False, "invalid input")],
    )

    with pytest.raises(ValueError, match="invalid input"):
        _run_validator(question, "bad", {}, raw="bad")


def test_apply_cli_answer_validates_single_choices() -> None:
    question = Question(
        key="license",
        prompt="License",
        choices=[("mit", "MIT"), ("apache", "Apache")],
    )

    assert _apply_cli_answer(question, "mit", {}) == "mit"

    with pytest.raises(ValueError, match="invalid choice"):
        _apply_cli_answer(question, "bsd", {})


def test_apply_cli_answer_validates_multiselect_choices() -> None:
    question = Question(
        key="workflows",
        prompt="Workflows",
        multiselect=True,
        choices=[("tests", "Tests"), ("lint", "Lint")],
        parser=lambda _raw, _answers: (_ for _ in ()).throw(AssertionError("parser not expected")),
    )

    assert _apply_cli_answer(question, ["tests", "lint"], {}) == ["tests", "lint"]

    with pytest.raises(ValueError, match="invalid choice\\(s\\)"):
        _apply_cli_answer(question, ["tests", "deploy"], {})


def test_fallback_default_values_and_choice_value_helpers() -> None:
    single = Question(key="license", prompt="License")
    multi = Question(key="workflows", prompt="Workflows", multiselect=True)

    assert _fallback_default_values(single, "mit") == ["mit"]
    assert _fallback_default_values(single, None) == []
    assert _fallback_default_values(multi, ["tests", "lint"]) == ["tests", "lint"]
    assert _as_choice_values("x") == ["x"]
    assert _as_choice_values(("a", "b")) == ["a", "b"]


def test_fallback_lookup_maps_and_token_resolution() -> None:
    value_map, label_map, index_map = _fallback_lookup_maps([("tests", "Tests"), ("lint", "Lint")])

    assert _resolve_fallback_token("1", value_map, label_map, index_map) == "tests"
    assert _resolve_fallback_token("lint", value_map, label_map, index_map) == "lint"
    assert _resolve_fallback_token("Tests", value_map, label_map, index_map) == "tests"
    assert _resolve_fallback_token("unknown", value_map, label_map, index_map) is None


def test_resolve_fallback_choice_uses_default_and_reports_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question = Question(key="license", prompt="License")
    style = Style()
    errors: list[str] = []
    monkeypatch.setattr(
        "sprout.prompt._print_error", lambda message, _style: errors.append(str(message))
    )

    resolved = _resolve_fallback_choice(
        question,
        "",
        ["mit"],
        {"mit": "mit"},
        {"mit": "mit"},
        {"1": "mit"},
        style,
    )
    assert resolved == "mit"

    unresolved = _resolve_fallback_choice(
        question,
        "",
        [],
        {"mit": "mit"},
        {"mit": "mit"},
        {"1": "mit"},
        style,
    )
    assert unresolved is None
    assert "Please choose a value." in errors


def test_prompt_for_text_noninteractive_retries_until_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: Iterator[str] = iter(["", "value"])
    errors: list[str] = []

    monkeypatch.setattr("sprout.prompt.supports_live_interaction", lambda: False)
    monkeypatch.setattr("sprout.prompt.console.input", lambda _prompt: next(responses))
    monkeypatch.setattr(
        "sprout.prompt._print_error", lambda message, _style: errors.append(str(message))
    )
    monkeypatch.setattr("sprout.prompt._print_text_summary", lambda _value, _style: None)

    question = Question(key="name", prompt="Project name")
    result = _prompt_for_text(question, None, {}, Style())

    assert result == "value"
    assert "Please provide a value." in errors


def test_fallback_choice_multiselect_retries_on_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: Iterator[str] = iter(["oops", "1,2"])
    errors: list[str] = []
    summaries: list[object] = []

    monkeypatch.setattr("sprout.prompt.console.input", lambda _prompt: next(responses))
    monkeypatch.setattr(
        "sprout.prompt._print_error", lambda message, _style: errors.append(str(message))
    )
    monkeypatch.setattr("sprout.prompt._print_fallback_choices", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "sprout.prompt._print_choice_summary",
        lambda _question, value, _map, _style: summaries.append(value),
    )

    question = Question(key="workflows", prompt="Workflows", multiselect=True)
    result = _fallback_choice(
        question,
        {},
        [],
        choices=[("tests", "Tests"), ("lint", "Lint")],
        style=Style(),
    )

    assert result == ["tests", "lint"]
    assert any("Unknown choice" in error for error in errors)
    assert summaries
    assert summaries[-1] == ["tests", "lint"]
