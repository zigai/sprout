from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sprout.errors import SproutPromptError
from sprout.prompt.processing import AnswerProcessor, ResolvedPrompt
from sprout.prompt.question import DefaultValue, Question
from sprout.prompt.style import Style
from sprout.prompt.terminal import (
    FallbackChoicePrompt,
    TerminalQuestion,
    highlight_prompt_line,
    print_choice_summary,
    print_error,
    print_text_summary,
    supports_live_interaction,
)


def collect_answers(
    questions: Sequence[Question],
    *,
    style: Style | None = None,
    initial_answers: dict[str, DefaultValue] | None = None,
) -> dict[str, DefaultValue]:
    style = style or Style()
    answers: dict[str, DefaultValue] = {}
    provided = dict(initial_answers or {})
    for question in questions:
        if question.key in provided and provided[question.key] is not None:
            raw_value = provided[question.key]
            try:
                answers[question.key] = AnswerProcessor(question, answers).process_cli(raw_value)
            except ValueError as e:
                raise SproutPromptError(f"{question.key}: {e}") from e

            continue

        try:
            should_ask = question.should_ask(answers)
        except (TypeError, ValueError) as e:
            raise SproutPromptError(f"{question.key}: {e}") from e

        if not should_ask:
            continue

        answers[question.key] = ask_question(question, answers, style)

    return answers


class QuestionPrompt:
    """Own the rendering and input workflow for one resolved question."""

    def __init__(
        self,
        question: Question,
        answers: dict[str, DefaultValue],
        style: Style,
    ) -> None:
        self.question = question
        self.answers = answers
        self.style = style
        self.resolved = ResolvedPrompt.from_question(question, answers)
        self.processor = AnswerProcessor(question, answers)
        self.terminal = TerminalQuestion(question, self.resolved, style)

    def ask(self) -> DefaultValue:
        if self.resolved.inline_choice_enabled and supports_live_interaction():
            selection = self.terminal.run_inline_application()
            raw_selection = selection if isinstance(selection, str) else str(selection)
            processed = self.processor.process(selection, raw=raw_selection)
            print_choice_summary(
                self.question,
                selection,
                dict(self.resolved.choices),
                self.style,
            )

            return processed

        self.terminal.print_header()
        if self.resolved.has_choices:
            return self._ask_choice()

        return self._ask_text()

    def _ask_choice(self) -> DefaultValue:
        choices = list(self.resolved.choices)
        if not choices:
            return self.resolved.default_value

        value_to_label = dict(choices)
        current_default = self.resolved.default_value

        while True:
            if not supports_live_interaction():
                return FallbackChoicePrompt(
                    question=self.question,
                    answers=self.answers,
                    default_value=current_default,
                    choices=choices,
                    value_to_label=value_to_label,
                    style=self.style,
                ).ask()

            selection = self.terminal.run_choice_application(choices, current_default)
            raw_selection = selection if isinstance(selection, str) else str(selection)
            try:
                processed = self.processor.process(selection, raw=raw_selection)
                print_choice_summary(
                    self.question,
                    selection,
                    value_to_label,
                    self.style,
                )
            except ValueError as e:
                print_error(e, self.style)
                current_default = selection
                continue

            return processed

    def _ask_text(self) -> DefaultValue:
        default_value = self.resolved.default_value

        while True:
            response = self.terminal.read_text_response(default_value)
            stripped = response.strip()
            if not stripped:
                if default_value in (None, []):
                    print_error("Please provide a value.", self.style)
                    continue

                candidate: DefaultValue = default_value
                parser_input = str(default_value)
            else:
                candidate = stripped
                parser_input = stripped

            try:
                candidate = self.processor.process(candidate, raw=parser_input)
                display_value = parser_input or str(candidate)
                if supports_live_interaction():
                    highlight_prompt_line(display_value, self.style)
                else:
                    print_text_summary(display_value, self.style)
            except ValueError as e:
                print_error(e, self.style)
                continue

            return candidate


def ask_question(
    question: Question,
    answers: dict[str, DefaultValue],
    style: Style,
) -> DefaultValue:
    return QuestionPrompt(question, answers, style).ask()


def confirm_overwrite(path: Path, *, style: Style) -> bool:
    if not supports_live_interaction():
        return False

    question = Question(
        key="overwrite",
        prompt=f"Allow overwriting files in '{path}'?",
        choices=[("yes", "Yes"), ("no", "No")],
        default="no",
    )

    return ask_question(question, {}, style) == "yes"


__all__ = ["QuestionPrompt", "ask_question", "collect_answers", "confirm_overwrite"]
