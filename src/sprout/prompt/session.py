from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from sprout.display import shorten_home
from sprout.errors import SproutPromptError
from sprout.prompt.layout import Layout, PromptKind, PromptView, Step, build_layout
from sprout.prompt.processing import AnswerProcessor, ResolvedPrompt
from sprout.prompt.question import DefaultValue, Question
from sprout.prompt.style import CompactStyle, Style
from sprout.prompt.terminal import (
    FallbackChoicePrompt,
    TerminalQuestion,
    choice_summary,
    console,
    print_answer,
    print_error,
    print_fragments,
    supports_live_interaction,
)


def _is_provided(question: Question, provided: Mapping[str, DefaultValue]) -> bool:
    return provided.get(question.key) is not None


def collect_answers(
    questions: Sequence[Question],
    *,
    style: Style | None = None,
    initial_answers: dict[str, DefaultValue] | None = None,
    title: str | None = None,
) -> dict[str, DefaultValue]:
    layout = build_layout(style or CompactStyle(), questions)
    answers: dict[str, DefaultValue] = {}
    provided = dict(initial_answers or {})
    asked = 0
    opened = False

    def open_frame() -> None:
        nonlocal opened

        if not opened:
            print_fragments(layout.start(title), layout)
            opened = True

    for position, question in enumerate(questions):
        if _is_provided(question, provided):
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

        open_frame()
        remaining = sum(
            later.when is not False and not _is_provided(later, provided)
            for later in questions[position:]
        )
        step = Step(index=asked + 1, total=asked + remaining)
        answers[question.key] = QuestionPrompt(question, answers, layout, step=step).ask()
        asked += 1

    if title:
        open_frame()

    if opened:
        print_fragments(layout.finish(), layout)

    return answers


def _prompt_kind(resolved: ResolvedPrompt, layout: Layout) -> PromptKind:
    if not resolved.has_choices:
        return "text"
    if resolved.question.multiselect:
        return "multiselect"
    if resolved.inline_choice_enabled and layout.confirm_width(resolved.choices) <= console.width:
        return "confirm"

    return "select"


class QuestionPrompt:
    """Own the rendering and input workflow for one resolved question."""

    def __init__(
        self,
        question: Question,
        answers: dict[str, DefaultValue],
        layout: Layout,
        *,
        step: Step | None = None,
    ) -> None:
        self.question = question
        self.answers = answers
        self.layout = layout
        self.resolved = ResolvedPrompt.from_question(question, answers)
        self.processor = AnswerProcessor(question, answers)
        default_value = self.resolved.default_value
        self.view = PromptView(
            question=question,
            kind=_prompt_kind(self.resolved, layout),
            choices=list(self.resolved.choices),
            placeholder="" if default_value in (None, "", []) else str(default_value),
            step=step,
        )
        self.terminal = TerminalQuestion(self.view, layout)

    def ask(self) -> DefaultValue:
        if self.resolved.has_choices:
            return self._ask_choice()

        return self._ask_text()

    def _ask_choice(self) -> DefaultValue:
        choices = self.view.choices
        if not choices:
            return self.resolved.default_value

        if not supports_live_interaction():
            self.terminal.print_header()

            return FallbackChoicePrompt(
                question=self.question,
                answers=self.answers,
                default_value=self.resolved.default_value,
                choices=choices,
                layout=self.layout,
            ).ask()

        current_default = self.resolved.default_value
        while True:
            selection = self.terminal.run_menu_application(current_default)
            raw_selection = ", ".join(selection) if isinstance(selection, list) else str(selection)
            try:
                processed = self.processor.process(selection, raw=raw_selection)
            except ValueError as e:
                self.view.error = str(e)
                current_default = selection
                continue

            print_answer(
                self.question,
                choice_summary(self.question, selection, dict(choices)),
                self.layout,
            )

            return processed

    def _ask_text(self) -> DefaultValue:
        default_value = self.resolved.default_value
        live = supports_live_interaction()
        if not live:
            self.terminal.print_header()

        typed = ""
        while True:
            response = (
                self.terminal.run_text_application(typed)
                if live
                else self.terminal.read_fallback_text()
            )
            stripped = response.strip()
            if not stripped:
                if default_value in (None, []):
                    self._report("Please provide a value.", live)
                    typed = ""
                    continue

                candidate: DefaultValue = default_value
                parser_input = str(default_value)
            else:
                candidate = stripped
                parser_input = stripped

            try:
                candidate = self.processor.process(candidate, raw=parser_input)
            except ValueError as e:
                self._report(str(e), live)
                typed = response
                continue

            print_answer(self.question, parser_input or str(candidate), self.layout)

            return candidate

    def _report(self, message: str, live: bool) -> None:
        if live:
            self.view.error = message
        else:
            print_error(message, self.layout)


def ask_question(
    question: Question,
    answers: dict[str, DefaultValue],
    style: Style,
) -> DefaultValue:
    return QuestionPrompt(question, answers, build_layout(style, [question])).ask()


def confirm_overwrite(path: Path, *, style: Style) -> bool:
    if not supports_live_interaction():
        return False

    question = Question(
        key="overwrite",
        prompt=f"Allow overwriting files in '{shorten_home(path)}'?",
        choices=[("yes", "Yes"), ("no", "No")],
        default="no",
    )

    return ask_question(question, {}, style) == "yes"


__all__ = ["QuestionPrompt", "ask_question", "collect_answers", "confirm_overwrite"]
