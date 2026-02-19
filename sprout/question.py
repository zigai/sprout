from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from sprout.validators import ValidatorType

AnswerMap = Mapping[str, object]
DefaultValue = object | None
DefaultFactory = Callable[[AnswerMap], DefaultValue]
ChoicesResolver = Callable[[AnswerMap], Sequence[tuple[str, str]]]
ParserType = Callable[[str, AnswerMap], object]

ChoicesType = Sequence[tuple[str, str]] | ChoicesResolver | None


@dataclass
class Question:
    key: str
    prompt: str
    help: str = ""
    default: DefaultValue | DefaultFactory = None
    choices: ChoicesType = None
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


__all__ = ["Question"]
