from __future__ import annotations

import inspect
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeGuard

from sprout.question import AnswerMap, DefaultValue, Question
from sprout.validators import ContextValidatorFn, ValidatorType

type Choice = tuple[str, str]


@dataclass(frozen=True)
class ResolvedPrompt:
    question: Question
    default_value: DefaultValue
    choices: list[Choice]

    @classmethod
    def from_question(cls, question: Question, answers: AnswerMap) -> ResolvedPrompt:
        return cls(
            question=question,
            default_value=question.resolve_default(answers),
            choices=list(question.resolve_choices(answers) or ()),
        )

    @property
    def has_choices(self) -> bool:
        return bool(self.choices)

    @property
    def inline_choice_enabled(self) -> bool:
        return len(self.choices) == 2 and not self.question.multiselect


@dataclass(frozen=True)
class AnswerProcessor:
    question: Question
    answers: AnswerMap

    def process(
        self,
        value: DefaultValue,
        *,
        raw: str | None = None,
        validator_raw: str | None = None,
    ) -> DefaultValue:
        processed = self.parse(value, raw=raw)
        self.validate(processed, raw=validator_raw if validator_raw is not None else raw)

        return processed

    def process_cli(self, value: DefaultValue) -> DefaultValue:
        raw_value, values = self._normalise_cli_values(value)
        self._validate_cli_choices(values)

        processed = values if self.question.multiselect else self.parse(value, raw=str(value))

        self.validate(processed, raw=raw_value)

        return processed

    def parse(self, value: DefaultValue, *, raw: str | None = None) -> DefaultValue:
        return apply_parser(self.question, value, self.answers, raw=raw)

    def validate(self, value: DefaultValue, *, raw: str | None = None) -> None:
        run_validator(self.question, value, self.answers, raw=raw)

    def _normalise_cli_values(self, value: DefaultValue) -> tuple[str, list[str]]:
        if self.question.multiselect:
            if isinstance(value, (list, tuple, set)):
                values = [str(item) for item in value]
            else:
                values = [str(value)]

            return ", ".join(values), values

        return str(value), [str(value)]

    def _validate_cli_choices(self, values: Sequence[str]) -> None:
        choices = self.question.resolve_choices(self.answers)
        if not choices:
            return

        allowed = {choice for choice, _label in choices}
        if self.question.multiselect:
            invalid = [item for item in values if item not in allowed]
            if invalid:
                raise ValueError(f"invalid choice(s): {', '.join(invalid)}")

            return

        if values[0] not in allowed:
            raise ValueError(f"invalid choice: {values[0]}")


def apply_parser(
    question: Question,
    value: DefaultValue,
    answers: AnswerMap,
    raw: str | None = None,
) -> DefaultValue:
    if question.parser and not question.multiselect:
        raw_value = raw if raw is not None else str(value)
        return question.parser(raw_value, answers)

    return value


def run_validator(
    question: Question,
    value: DefaultValue,
    answers: AnswerMap,
    raw: str | None = None,
) -> None:
    if not question.validators:
        return

    candidate_answers = dict(answers)
    candidate_answers[question.key] = value
    raw_value = raw if raw is not None else str(value)

    for validator in question.validators:
        if validator_accepts_answers(validator):
            valid, message = validator(raw_value, candidate_answers)
        else:
            valid, message = validator(raw_value)  # pyrefly: ignore[bad-argument-count]

        if not valid:
            raise ValueError(message or "invalid value.")


def validator_accepts_answers(validator: ValidatorType) -> TypeGuard[ContextValidatorFn]:
    try:
        signature = inspect.signature(validator)
    except (TypeError, ValueError) as error:
        raise ValueError(f"failed to inspect validator: {error}") from error

    parameters = tuple(signature.parameters.values())
    positional = tuple(
        parameter
        for parameter in parameters
        if parameter.kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }
    )
    has_varargs = any(
        parameter.kind is inspect.Parameter.VAR_POSITIONAL for parameter in parameters
    )

    if has_varargs or len(positional) >= 2:
        return True
    if len(positional) == 1:
        return False

    raise ValueError("validator must accept value or value and answers.")


__all__ = [
    "AnswerProcessor",
    "Choice",
    "ResolvedPrompt",
    "apply_parser",
    "run_validator",
    "validator_accepts_answers",
]
