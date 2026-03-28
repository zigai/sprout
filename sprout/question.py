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
    """
    Parse a yes-or-no string and return a boolean value.

    Args:
        value (str): Raw answer text.
        _answers (AnswerMap): Previously collected answers. This parameter is unused.

    Raises:
        ValueError: If `value` is not one of yes/y/true/1/no/n/false/0.
    """
    normalized = value.strip().lower()
    if normalized in {"yes", "y", "true", "1"}:
        return True

    if normalized in {"no", "n", "false", "0"}:
        return False

    raise ValueError("expected yes or no.")


@dataclass
class Question:
    """
    Define one prompt and its answer-processing rules.

    Attributes:
        key (str): Stable answer key used in the returned answers mapping.
        prompt (str): Prompt text shown to the user.
        help (str): Optional helper text shown with the prompt. Defaults to an empty string.
        default (DefaultValue | DefaultFactory): Default answer value or callable that derives one
            from previously collected answers. Defaults to None.
        choices (ChoicesType): Optional static or dynamic list of `(value, label)` choices.
            Defaults to None.
        when (WhenType): Boolean or callable gate that controls whether to ask this question.
            Defaults to True.
        multiselect (bool): Whether this question accepts multiple selected values.
            Defaults to False.
        parser (ParserType | None): Optional parser that converts raw text into a typed value.
            Defaults to None.
        validators (Sequence[ValidatorType]): Validators that run after parsing. Defaults to an
            empty list.
    """

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
        """
        Resolve and return the default value for this question.

        Args:
            answers (AnswerMap): Previously collected answers used by dynamic defaults.
        """
        return self.default(answers) if callable(self.default) else self.default

    def resolve_choices(self, answers: AnswerMap) -> Sequence[tuple[str, str]] | None:
        """
        Resolve and return available choices for this question.

        Args:
            answers (AnswerMap): Previously collected answers used by dynamic choices.
        """
        choices = self.choices(answers) if callable(self.choices) else self.choices

        if choices is None:
            return None

        return list(choices)

    def should_ask(self, answers: AnswerMap) -> bool:
        """
        Evaluate and return whether this question should be asked.

        Args:
            answers (AnswerMap): Previously collected answers passed to conditional logic.

        Raises:
            ValueError: If evaluating a callable condition raises an exception.
            TypeError: If the condition result is not a bool.
        """
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
        """
        Build a yes-or-no question with built-in parsing.

        Args:
            key (str): Answer key used in the returned answers mapping.
            prompt (str): Prompt text shown to the user.
            help_text (str): Optional helper text shown with the prompt.
            default (bool): Default yes/no selection. True maps to "yes", False maps to "no".
            when (WhenType): Boolean or callable gate that controls whether to ask the question.
            validators (Sequence[ValidatorType]): Validators that run after parsing.
        """
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
