from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style as PTStyle
from rich.console import Console
from rich.control import Control, ControlType  # type:ignore
from rich.text import Text

from .question import Question
from .style import Style

if TYPE_CHECKING:
    from prompt_toolkit.key_binding.key_processor import KeyPressEvent


console = Console()


def collect_answers(
    questions: Sequence[Question],
    *,
    style: Style | None = None,
    initial_answers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    style = style or Style()
    answers: dict[str, Any] = dict(initial_answers or {})
    for question in questions:
        answers[question.key] = ask_question(question, answers, style)
    return answers


def ask_question(question: Question, answers: dict[str, Any], style: Style) -> Any:
    default_value = question.resolve_default(answers)

    choices = question.choices
    inline_choice_enabled = choices is not None and len(choices) == 2 and not question.multiselect

    if inline_choice_enabled and supports_live_interaction():
        assert choices is not None
        inline_choices = list(choices)
        selection = _prompt_toolkit_inline_choice(
            question,
            inline_choices,
            default_value,
            style,
        )
        processed = _apply_parser(question, selection, answers)
        raw_selection = selection if isinstance(selection, str) else str(selection)
        _run_validator(question, processed, answers, raw_selection)
        value_to_label: dict[Any, str | None] = {value: label for value, label in inline_choices}
        _print_choice_summary(question, selection, value_to_label, style)
        return processed

    inline_preview = ""

    if inline_choice_enabled and choices:
        inline_preview = _format_inline_preview(question, default_value, style)

    header = Text()
    header.append(style.prompt.prefix, style=style.prompt.prefix_style)
    question_text = Text(question.prompt, style=style.prompt.text_style)
    question_text.stylize("bold")
    header += question_text

    if question.help:
        header.append(f" — {question.help}", style=style.prompt.help_style)

    instruction = (
        style.menu.instruction_multi if question.multiselect else style.menu.instruction_single
    )

    if question.choices and instruction:
        header.append("  ")
        header.append(instruction, style=style.menu.instruction_style)

    if inline_preview:
        header.append(" ")
        header.append(inline_preview, style=style.default_style)

    console.print(header)

    if question.choices:
        return _interactive_choice(question, answers, default_value, style)

    return _prompt_for_text(question, default_value, answers, style)


def confirm_overwrite(path: Path, *, style: Style) -> bool:
    if not supports_live_interaction():
        return False

    question = Question(
        key="overwrite",
        prompt=f"Allow overwriting files in {path}?",
        choices=[("yes", "Yes"), ("no", "No")],
        default="no",
    )
    answer = ask_question(question, {}, style)
    return answer == "yes"


def _interactive_choice(
    question: Question,
    answers: dict[str, Any],
    default_value: Any,
    style: Style,
) -> Any:
    choices = list(question.choices or [])
    if not choices:
        return default_value

    value_to_label: dict[Any, str | None] = {value: label for value, label in choices}
    current_default = default_value

    while True:
        if supports_live_interaction():
            selection = _prompt_toolkit_choice(question, choices, current_default, style)
        else:
            return _fallback_choice(
                question,
                answers,
                current_default,
                choices,
                value_to_label,
                style,
            )

        processed = _apply_parser(question, selection, answers)
        raw_selection = selection if isinstance(selection, str) else str(selection)
        try:
            _run_validator(question, processed, answers, raw_selection)
            _print_choice_summary(question, selection, value_to_label, style)
        except ValueError as error:
            _print_error(error, style)
            current_default = selection
        else:
            return processed


def _prompt_for_text(
    question: Question,
    default_value: Any,
    answers: dict[str, Any],
    style: Style,
) -> Any:
    while True:
        if supports_live_interaction():
            session = PromptSession()
            has_default = default_value not in (None, "", [])
            prompt_kwargs: dict[str, Any] = {}
            if has_default:
                default_str = str(default_value)
                prompt_kwargs["placeholder"] = default_str
                prompt_kwargs["key_bindings"] = _placeholder_key_bindings(default_str)
            try:
                response = session.prompt(f"{style.input_prefix} ", **prompt_kwargs)
            except KeyboardInterrupt:  # pragma: no cover - user abort
                raise
        else:
            response = console.input(f"[bold green]{style.input_prefix} [/bold green]").strip()

        stripped = response.strip()

        if not stripped:
            if default_value in (None, "", []):
                _print_error("Please provide a value.", style)
                continue

            candidate: Any = default_value
            parser_input = str(default_value)
        else:
            candidate = stripped
            parser_input = stripped

        try:
            candidate = _apply_parser(question, candidate, answers, parser_input)
            _run_validator(question, candidate, answers, parser_input)
            display_value = parser_input if parser_input else str(candidate)

            if supports_live_interaction():
                _highlight_prompt_line(display_value, style)
            else:
                _print_text_summary(display_value, style)
        except ValueError as error:
            _print_error(error, style)
        else:
            return candidate


def _format_inline_preview(question: Question, default_value: Any, style: Style) -> str:
    if not question.choices:
        return ""

    parts = []
    for value, label in question.choices:
        icon = (
            style.inline.selected_icon if value == default_value else style.inline.unselected_icon
        )
        parts.append(f"{icon} {label or value}")

    return style.inline.separator.join(parts)


def _prompt_toolkit_choice(
    question: Question,
    choices: Sequence[tuple[str, str]],
    default_value: Any,
    style: Style,
) -> Any:
    items = list(choices)
    if not items:
        return default_value

    value_to_index = {value: idx for idx, (value, _) in enumerate(items)}
    selected_indices: set[int]

    if question.multiselect:
        default_values = (
            list(default_value) if isinstance(default_value, (list, tuple, set)) else []
        )
        selected_indices = {
            value_to_index[value] for value in default_values if value in value_to_index
        }
        pointer = min(selected_indices) if selected_indices else 0
    else:
        selected_indices = set()
        pointer = value_to_index.get(default_value, 0)

    pointer_box = [pointer]
    selected_box = set(selected_indices)

    pt_style = PTStyle.from_dict(
        {
            "title": style.prompt.text_style,
            "hint": style.menu.instruction_style,
            "caret": style.menu.caret_style,
            "bullet.sel": style.menu.bullet_selected_style,
            "bullet": style.menu.bullet_unselected_style,
            "text.sel": style.menu.text_selected_style,
            "text": style.menu.text_unselected_style,
        }
    )

    def _render() -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        for idx, (value, label) in enumerate(items):
            caret = (
                style.menu.caret_icon if idx == pointer_box[0] else " " * len(style.menu.caret_icon)
            )
            caret_style = "class:caret" if idx == pointer_box[0] else ""

            if question.multiselect:
                bullet_selected = idx in selected_box
            else:
                bullet_selected = idx == pointer_box[0]

            bullet_style = "class:bullet.sel" if bullet_selected else "class:bullet"
            bullet = (
                style.menu.bullet_selected_icon
                if bullet_selected
                else style.menu.bullet_unselected_icon
            )
            text_style = "class:text.sel" if idx == pointer_box[0] else "class:text"

            display = label or value
            fragments.append((caret_style, caret))
            fragments.append((bullet_style, bullet))
            fragments.append((text_style, str(display)))
            if idx != len(items) - 1:
                fragments.append(("", "\n"))

        return fragments

    body_control = FormattedTextControl(_render)
    body = Window(content=body_control, always_hide_cursor=True)

    app = Application(
        layout=Layout(HSplit([body])),
        key_bindings=_choice_key_bindings(pointer_box, selected_box, items, question),
        mouse_support=False,
        full_screen=False,
        style=pt_style,
    )

    result = app.run()

    if result is None:
        if question.multiselect:
            return [items[idx][0] for idx in sorted(selected_indices)]
        return default_value

    return result


def _choice_key_bindings(
    pointer_box: list[int],
    selected_box: set[int],
    items: Sequence[tuple[str, str]],
    question: Question,
) -> KeyBindings:
    keybind = KeyBindings()

    @keybind.add("up")
    @keybind.add("k")
    def _go_up(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        pointer_box[0] = (pointer_box[0] - 1) % len(items)
        event.app.invalidate()

    @keybind.add("down")
    @keybind.add("j")
    def _go_down(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        pointer_box[0] = (pointer_box[0] + 1) % len(items)
        event.app.invalidate()

    @keybind.add("left")
    @keybind.add("h")
    def _go_left(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        pointer_box[0] = (pointer_box[0] - 1) % len(items)
        event.app.invalidate()

    @keybind.add("right")
    @keybind.add("l")
    def _go_right(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        pointer_box[0] = (pointer_box[0] + 1) % len(items)
        event.app.invalidate()

    @keybind.add("home")
    def _go_home(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        pointer_box[0] = 0
        event.app.invalidate()

    @keybind.add("end")
    def _go_end(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        pointer_box[0] = len(items) - 1
        event.app.invalidate()

    if question.multiselect:

        @keybind.add(" ")
        def _toggle(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
            idx = pointer_box[0]
            if idx in selected_box:
                selected_box.remove(idx)
            else:
                selected_box.add(idx)
            event.app.invalidate()

    @keybind.add("enter")
    def _confirm(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        if question.multiselect:
            result = [items[idx][0] for idx in sorted(selected_box)]
        else:
            result = items[pointer_box[0]][0]
        event.app.exit(result=result)

    @keybind.add("c-c")
    def _interrupt(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        event.app.exit(exception=KeyboardInterrupt)

    return keybind


def _prompt_toolkit_inline_choice(
    question: Question,
    choices: Sequence[tuple[str, str]],
    default_value: Any,
    style: Style,
) -> Any:
    items = list(choices)
    value_to_index = {value: idx for idx, (value, _) in enumerate(items)}
    pointer = value_to_index.get(default_value, 0)
    pointer_box = [pointer]

    pt_style = PTStyle.from_dict(
        {
            "prompt": style.prompt.text_style,
            "bullet.sel": style.inline.bullet_selected_style,
            "bullet": style.inline.bullet_unselected_style,
            "text.sel": style.inline.text_selected_style,
            "text": style.inline.text_unselected_style,
        }
    )

    def _render() -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        fragments.append(("class:prompt", f"{style.prompt.prefix}{question.prompt} "))
        for idx, (value, label) in enumerate(items):
            selected = idx == pointer_box[0]
            bullet_style = "class:bullet.sel" if selected else "class:bullet"
            bullet = style.inline.selected_icon if selected else style.inline.unselected_icon
            text_style = "class:text.sel" if selected else "class:text"
            display = label or value

            fragments.append((bullet_style, bullet))
            fragments.append(("", " "))
            fragments.append((text_style, str(display)))
            if idx != len(items) - 1:
                fragments.append(("", style.inline.separator))

        return fragments

    body_control = FormattedTextControl(_render)
    body = Window(content=body_control, height=1, always_hide_cursor=True)

    keybind = KeyBindings()

    @keybind.add("left")
    @keybind.add("h")
    @keybind.add("up")
    def _go_left(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        pointer_box[0] = (pointer_box[0] - 1) % len(items)
        event.app.invalidate()

    @keybind.add("right")
    @keybind.add("l")
    @keybind.add("down")
    def _go_right(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        pointer_box[0] = (pointer_box[0] + 1) % len(items)
        event.app.invalidate()

    @keybind.add("enter")
    def _confirm(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        event.app.exit(result=items[pointer_box[0]][0])

    @keybind.add("c-c")
    def _interrupt(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        event.app.exit(exception=KeyboardInterrupt)

    app = Application(
        layout=Layout(HSplit([body])),
        key_bindings=keybind,
        mouse_support=False,
        full_screen=False,
        style=pt_style,
    )

    result = app.run()
    if result is None:
        return default_value
    return result


def _fallback_choice(
    question: Question,
    answers: dict[str, Any],
    default_value: Any,
    choices: Sequence[tuple[str, str]] | None = None,
    value_to_label: dict[Any, str | None] | None = None,
    style: Style | None = None,
) -> Any:
    style = style or Style()
    choices = list(choices or question.choices or [])
    if not choices:
        return default_value

    mapping: dict[Any, str | None] = value_to_label or {value: label for value, label in choices}

    for idx, (value, label) in enumerate(choices, start=1):
        line = Text()
        line.append(f"  {idx}) ", style=style.default_style)
        line.append(_choice_label(value, label), style="white")
        console.print(line)

    if question.multiselect:
        console.print(
            Text(
                "  Enter comma-separated numbers or values",
                style=style.menu.instruction_style,
            )
        )

    value_map = {str(value).lower(): value for value, _ in choices}
    label_map = {str(label).lower(): value for value, label in choices}
    index_map = {str(idx): value for idx, (value, _) in enumerate(choices, start=1)}

    default_list: list[Any] = []
    if question.multiselect:
        if isinstance(default_value, (list, tuple, set)):
            default_list = list(default_value)
    elif default_value not in (None, "", []):
        default_list = [default_value]

    if default_list:
        console.print(
            Text(
                "  default: "
                + ", ".join(
                    _choice_label(str(value), mapping.get(value, str(value)))
                    for value in default_list
                ),
                style=style.default_style,
            )
        )

    while True:
        response = console.input(f"[bold green]{style.input_prefix} [/bold green]").strip()

        candidate: Any
        if not response:
            if question.multiselect:
                candidate = list(default_list)
            elif default_list:
                candidate = default_list[0]
            else:
                _print_error("Please choose a value.", style)
                continue
        else:
            if question.multiselect:
                tokens = [token.strip() for token in response.split(",") if token.strip()]
                resolved: list[str] = []
                invalid = False

                for token in tokens:
                    lower = token.lower()
                    if token in index_map:
                        resolved.append(index_map[token])
                    elif lower in value_map:
                        resolved.append(value_map[lower])
                    elif lower in label_map:
                        resolved.append(label_map[lower])
                    else:
                        _print_error(f"Unknown choice '{token}'.", style)
                        invalid = True
                        break

                if invalid:
                    continue

                candidate = resolved
            else:
                token = response
                lower = token.lower()

                if token in index_map:
                    candidate = index_map[token]
                elif lower in value_map:
                    candidate = value_map[lower]
                elif lower in label_map:
                    candidate = label_map[lower]
                else:
                    candidate = response

        display_candidate = candidate
        processed: Any = candidate
        raw_value = response if response else str(candidate)

        if question.parser and not question.multiselect:
            processed = question.parser(str(candidate), answers)

        try:
            _run_validator(question, processed, answers, raw_value)
        except ValueError as error:
            _print_error(error, style)
        else:
            if question.multiselect:
                processed_list = list(processed)
                _print_choice_summary(question, processed_list, mapping, style)
                return processed_list

            _print_choice_summary(question, display_candidate, mapping, style)
            return processed


def _print_choice_summary(
    question: Question,
    value: Any,
    value_to_label: dict[Any, str | None],
    style: Style,
) -> None:
    if question.multiselect:
        items = value if isinstance(value, (list, tuple, set)) else [value]
        labels = [_choice_label(str(item), value_to_label.get(item, str(item))) for item in items]
        summary = ", ".join(labels) if labels else "none"

        if labels:
            summary_style = style.summary.selected_style
        else:
            summary_style = style.summary.dim_style
    else:
        summary = _choice_label(str(value), value_to_label.get(value, str(value)))
        summary_style = style.summary.selected_style
    console.print(Text(f"{style.summary.prefix}{summary}", style=summary_style))


def _print_text_summary(value: Any, style: Style) -> None:
    console.print(Text(f"{style.summary.prefix}{value}", style=style.summary.selected_style))


def _highlight_prompt_line(value: str, style: Style) -> None:
    styled = Text(f"{style.input_prefix} {value}", style=style.summary.selected_style)
    controls = (
        Control((ControlType.CURSOR_UP, 1)),
        Control(ControlType.CARRIAGE_RETURN),
        Control((ControlType.ERASE_IN_LINE, 2)),
    )
    console.control(*controls)
    console.print(styled)


def _placeholder_key_bindings(default_text: str) -> KeyBindings:
    keybind = KeyBindings()

    def populate(buffer) -> bool:
        if buffer.text:
            return False
        buffer.insert_text(default_text)
        return True

    @keybind.add("left")
    def _(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        buffer = event.app.current_buffer
        populate(buffer)
        if buffer.cursor_position > 0:
            buffer.cursor_left(count=1)

    @keybind.add("right")
    def _(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        buffer = event.app.current_buffer
        inserted = populate(buffer)
        if not inserted:
            buffer.cursor_right(count=1)

    @keybind.add("home")
    def _(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        buffer = event.app.current_buffer
        populate(buffer)
        buffer.cursor_position = 0

    @keybind.add("end")
    def _(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        buffer = event.app.current_buffer
        populate(buffer)
        buffer.cursor_position = len(buffer.text)

    @keybind.add("backspace")
    @keybind.add("c-h")
    def _(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        buffer = event.app.current_buffer
        populate(buffer)
        if buffer.text:
            buffer.delete_before_cursor(count=1)

    @keybind.add("delete")
    @keybind.add("c-d")
    def _(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        buffer = event.app.current_buffer
        populate(buffer)
        if buffer.text:
            buffer.delete(count=1)

    @keybind.add("c-c")
    def _(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        event.app.exit(exception=KeyboardInterrupt)

    return keybind


def _apply_parser(
    question: Question,
    value: Any,
    answers: dict[str, Any],
    raw: str | None = None,
) -> Any:
    if question.parser and not question.multiselect:
        raw_value = raw if raw is not None else str(value)
        return question.parser(raw_value, answers)
    return value


def _run_validator(
    question: Question,
    value: Any,
    answers: dict[str, Any],
    raw: str | None = None,
) -> None:
    if not question.validators:
        return

    candidate_answers = dict(answers)
    candidate_answers[question.key] = value
    raw_value = raw if raw is not None else str(value)

    for validator in question.validators:
        try:
            valid, message = validator(raw_value, candidate_answers)
        except TypeError:
            valid, message = validator(raw_value)

        if not valid:
            raise ValueError(message or "invalid value.")


def _choice_label(value: str, label: str | None) -> str:
    return label or value


def supports_live_interaction() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _print_error(message: Any, style: Style) -> None:
    console.print(f"[{style.error.style}]{style.error.label}[/] {message}")


__all__ = [
    "ask_question",
    "collect_answers",
    "console",
    "supports_live_interaction",
    "confirm_overwrite",
]
