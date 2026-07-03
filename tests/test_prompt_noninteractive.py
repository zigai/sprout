from __future__ import annotations

from collections.abc import Iterator

import pytest

from sprout.prompt import (
    DefaultPlaceholderBindings,
    FallbackChoicePrompt,
    _apply_cli_answer,
    _apply_parser,
    _as_choice_values,
    _fallback_default_values,
    _fallback_lookup_maps,
    _prompt_for_text,
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


def test_run_validator_preserves_validator_type_error() -> None:
    def broken_validator(_raw: str, _answers: dict[str, object]) -> tuple[bool, str | None]:
        raise TypeError("validator bug")

    question = Question(
        key="name",
        prompt="Name",
        validators=[broken_validator],
    )

    with pytest.raises(TypeError, match="validator bug"):
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
    choices = [("tests", "Tests"), ("lint", "Lint")]
    value_map, label_map, index_map = _fallback_lookup_maps(choices)

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
        "sprout.prompt._print_error", lambda message, _style: errors.append(str(message))
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

    monkeypatch.setattr("sprout.prompt.supports_live_interaction", lambda: False)
    monkeypatch.setattr("sprout.prompt.console.input", lambda _prompt: "")
    monkeypatch.setattr(
        "sprout.prompt._print_error", lambda message, _style: errors.append(str(message))
    )
    monkeypatch.setattr(
        "sprout.prompt._print_text_summary", lambda value, _style: summaries.append(value)
    )

    question = Question(key="description", prompt="Description")
    result = _prompt_for_text(question, "", {}, Style())

    assert result == ""
    assert summaries == [""]
    assert errors == []


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
