from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from sprout.validators import ValidatorType

AnswerMap = Mapping[str, object]
DefaultValue = object | None
DefaultFactory = Callable[[AnswerMap], DefaultValue]
ChoicesResolver = Callable[[AnswerMap], Sequence[tuple[str, str]]]
ParserType = Callable[[str, AnswerMap], object]
WhenResolver = Callable[[AnswerMap], bool]

ChoicesType = Sequence[tuple[str, str]] | ChoicesResolver | None
WhenType = bool | WhenResolver

YES_NO_CHOICES: tuple[tuple[str, str], tuple[str, str]] = (
    ("yes", "Yes"),
    ("no", "No"),
)


def parse_yes_no(value: str, _answers: AnswerMap) -> bool:
    normalized = value.strip().lower()
    if normalized in {"yes", "y", "true", "1"}:
        return True
    if normalized in {"no", "n", "false", "0"}:
        return False
    raise ValueError("expected yes or no.")


@dataclass
class Question:
    key: str
    prompt: str
    help: str = ""
    default: DefaultValue | DefaultFactory = None
    choices: ChoicesType = None
    when: WhenType = True
    multiselect: bool = False
    parser: ParserType | None = None
    validators: Sequence[ValidatorType] = field(default_factory=list)

    def resolve_default(self, answers: AnswerMap) -> DefaultValue:
        return self.default(answers) if callable(self.default) else self.default

    def resolve_choices(self, answers: AnswerMap) -> Sequence[tuple[str, str]] | None:
        choices = self.choices(answers) if callable(self.choices) else self.choices

        if choices is None:
            return None

        return list(choices)

    def should_ask(self, answers: AnswerMap) -> bool:
        if callable(self.when):
            try:
                result = self.when(answers)
            except Exception as error:
                raise ValueError(f"failed to evaluate condition: {error}") from error
        else:
            result = self.when

        if not isinstance(result, bool):
            got = type(result).__name__
            raise TypeError(f"condition must return a bool, got {got}.")

        return result

    @classmethod
    def yes_no(
        cls,
        *,
        key: str,
        prompt: str,
        help_text: str = "",
        default: bool = True,
        when: WhenType = True,
        validators: Sequence[ValidatorType] = (),
    ) -> Question:
        return cls(
            key=key,
            prompt=prompt,
            help=help_text,
            default="yes" if default else "no",
            choices=YES_NO_CHOICES,
            when=when,
            parser=parse_yes_no,
            validators=list(validators),
        )


__all__ = ["YES_NO_CHOICES", "Question", "parse_yes_no"]
