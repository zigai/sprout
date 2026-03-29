from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style as PTStyle
from rich.console import Console
from rich.control import Control, ControlType
from rich.text import Text

from sprout.question import Question
from sprout.style import Style

if TYPE_CHECKING:
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.key_binding.key_processor import KeyPressEvent


console = Console()
type Choice = tuple[str, str]
type ChoiceLabelMap = Mapping[str, str | None]
type ChoiceChoiceMap = dict[str, str | None]


def collect_answers(
    questions: Sequence[Question],
    *,
    style: Style | None = None,
    initial_answers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Collect answers for each question in order and return the resulting mapping.

    Args:
        questions (Sequence[Question]): Questions to evaluate and optionally prompt for.
        style (Style | None): Optional style overrides used for interactive prompting.
        initial_answers (dict[str, Any] | None): Optional CLI-provided answers keyed by question
            key. Non-None values bypass interactive prompts.

    Raises:
        SystemExit: If a CLI-provided answer is invalid or a `when` condition fails validation.
    """
    style = style or Style()
    answers: dict[str, Any] = {}
    provided = dict(initial_answers or {})
    for question in questions:
        if question.key in provided and provided[question.key] is not None:
            raw_value = provided[question.key]
            try:
                answers[question.key] = _apply_cli_answer(question, raw_value, answers)
            except ValueError as error:
                raise SystemExit(f"{question.key}: {error}") from error

            continue

        try:
            should_ask = question.should_ask(answers)
        except (TypeError, ValueError) as error:
            raise SystemExit(f"{question.key}: {error}") from error

        if not should_ask:
            continue

        answers[question.key] = ask_question(question, answers, style)

    return answers


def ask_question(question: Question, answers: dict[str, Any], style: Style) -> object:
    """
    Prompt for one question and return the parsed answer value.

    Args:
        question (Question): Question definition including parsing and validation rules.
        answers (dict[str, Any]): Previously collected answers used for dynamic behavior.
        style (Style): Prompt rendering configuration.

    Raises:
        ValueError: If inline-choice parsing or validation fails.
    """
    default_value = question.resolve_default(answers)

    # resolve dynamic choices
    resolved_choices = question.resolve_choices(answers)
    choices: list[Choice] = list(resolved_choices) if resolved_choices is not None else []
    inline_choice_enabled = len(choices) == 2 and not question.multiselect

    if inline_choice_enabled and supports_live_interaction():
        selection = _prompt_toolkit_inline_choice(
            question,
            choices,
            default_value,
            style,
        )
        processed = _apply_parser(question, selection, answers)
        raw_selection = selection if isinstance(selection, str) else str(selection)
        _run_validator(question, processed, answers, raw_selection)
        value_to_label = dict(choices)
        _print_choice_summary(question, selection, value_to_label, style)

        return processed

    inline_preview = ""

    if inline_choice_enabled and choices:
        inline_preview = _format_inline_preview(default_value, style, choices)

    header = Text()
    header.append(style.prompt.prefix, style=style.prompt.prefix_style)
    question_text = Text(question.prompt, style=style.prompt.text_style)
    question_text.stylize("bold")
    header += question_text

    if question.help:
        header.append(f" - {question.help}", style=style.prompt.help_style)

    instruction = (
        style.menu.instruction_multi if question.multiselect else style.menu.instruction_single
    )

    if choices and instruction:
        header.append("  ")
        header.append(instruction, style=style.menu.instruction_style)

    if inline_preview:
        header.append(" ")
        header.append(inline_preview, style=style.default_style)

    console.print(header)

    if choices:
        return _interactive_choice(question, answers, default_value, style, choices)

    return _prompt_for_text(question, default_value, answers, style)


def confirm_overwrite(path: Path, *, style: Style) -> bool:
    """
    Ask for overwrite confirmation and return whether to continue.

    Args:
        path (Path): Destination path shown in the confirmation prompt.
        style (Style): Prompt rendering configuration.
    """
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
    default_value: object,
    style: Style,
    choices: Sequence[Choice],
) -> object:
    choices = list(choices or [])
    if not choices:
        return default_value

    value_to_label = dict(choices)
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
    default_value: object,
    answers: dict[str, Any],
    style: Style,
) -> object:
    while True:
        if supports_live_interaction():
            session: PromptSession[str] = PromptSession()
            has_default = default_value not in (None, "", [])
            prompt_kwargs: dict[str, Any] = {}

            if has_default:
                default_str = str(default_value)
                prompt_kwargs["placeholder"] = default_str
                prompt_kwargs["key_bindings"] = _placeholder_key_bindings(default_str)

            response = session.prompt(f"{style.input_prefix} ", **prompt_kwargs)
        else:
            response = console.input(f"[bold green]{style.input_prefix} [/bold green]").strip()

        stripped = response.strip()

        if not stripped:
            if default_value in (None, "", []):
                _print_error("Please provide a value.", style)
                continue

            candidate: object = default_value
            parser_input = str(default_value)
        else:
            candidate = stripped
            parser_input = stripped

        try:
            candidate = _apply_parser(question, candidate, answers, parser_input)
            _run_validator(question, candidate, answers, parser_input)
            display_value = parser_input or str(candidate)

            if supports_live_interaction():
                _highlight_prompt_line(display_value, style)
            else:
                _print_text_summary(display_value, style)
        except ValueError as error:
            _print_error(error, style)
        else:
            return candidate


def _format_inline_preview(
    default_value: object,
    style: Style,
    choices: Sequence[Choice],
) -> str:
    if not choices:
        return ""

    parts = []
    for value, label in choices:
        icon = (
            style.inline.selected_icon if value == default_value else style.inline.unselected_icon
        )
        parts.append(f"{icon} {label or value}")

    return style.inline.separator.join(parts)


def _prompt_toolkit_choice(
    question: Question,
    choices: Sequence[Choice],
    default_value: object,
    style: Style,
) -> object:
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
        pointer = value_to_index.get(default_value, 0) if isinstance(default_value, str) else 0

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
            bullet_selected = idx in selected_box if question.multiselect else idx == pointer_box[0]

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

    app: Application[object] = Application(
        layout=Layout(HSplit([body])),
        key_bindings=_choice_key_bindings(
            pointer_box,
            selected_box,
            items,
            multiselect=question.multiselect,
        ),
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


def _bind_choice_move_key(
    keybind: KeyBindings,
    key: str,
    pointer_box: list[int],
    item_count: int,
    *,
    delta: int | None = None,
    position: int | None = None,
) -> None:
    @keybind.add(key)
    def _move(
        event: KeyPressEvent,
        _delta: int | None = delta,
        _position: int | None = position,
    ) -> None:  # pragma: no cover - interactive
        if _position is None:
            pointer_box[0] = (pointer_box[0] + (_delta or 0)) % item_count
        elif _position < 0:
            pointer_box[0] = item_count - 1
        else:
            pointer_box[0] = _position

        event.app.invalidate()


def _bind_choice_toggle_key(
    keybind: KeyBindings,
    pointer_box: list[int],
    selected_box: set[int],
) -> None:
    @keybind.add(" ")
    def _toggle(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        idx = pointer_box[0]
        if idx in selected_box:
            selected_box.remove(idx)
        else:
            selected_box.add(idx)

        event.app.invalidate()


def _bind_choice_confirm_key(
    keybind: KeyBindings,
    pointer_box: list[int],
    selected_box: set[int],
    items: Sequence[Choice],
    *,
    multiselect: bool,
) -> None:
    @keybind.add("enter")
    def _confirm(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        if multiselect:
            result: str | list[str] = [items[idx][0] for idx in sorted(selected_box)]
        else:
            result = items[pointer_box[0]][0]

        event.app.exit(result=result)


def _bind_interrupt_key(keybind: KeyBindings) -> None:
    @keybind.add("c-c")
    def _interrupt(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        event.app.exit(exception=KeyboardInterrupt)


def _choice_key_bindings(
    pointer_box: list[int],
    selected_box: set[int],
    items: Sequence[Choice],
    *,
    multiselect: bool,
) -> KeyBindings:
    keybind = KeyBindings()
    item_count = len(items)
    for key in ("up", "k", "left", "h"):
        _bind_choice_move_key(keybind, key, pointer_box, item_count, delta=-1)

    for key in ("down", "j", "right", "l"):
        _bind_choice_move_key(keybind, key, pointer_box, item_count, delta=1)

    _bind_choice_move_key(keybind, "home", pointer_box, item_count, position=0)
    _bind_choice_move_key(keybind, "end", pointer_box, item_count, position=-1)

    if multiselect:
        _bind_choice_toggle_key(keybind, pointer_box, selected_box)

    _bind_choice_confirm_key(
        keybind,
        pointer_box,
        selected_box,
        items,
        multiselect=multiselect,
    )
    _bind_interrupt_key(keybind)

    return keybind


def _prompt_toolkit_inline_choice(
    question: Question,
    choices: Sequence[Choice],
    default_value: object,
    style: Style,
) -> object:
    items = list(choices)
    value_to_index = {value: idx for idx, (value, _) in enumerate(items)}
    pointer = value_to_index.get(default_value, 0) if isinstance(default_value, str) else 0
    pointer_box = [pointer]

    pt_style = PTStyle.from_dict(
        {
            "prompt": style.prompt.text_style,
            "prefix": style.prompt.prefix_style,
            "bullet.sel": style.inline.bullet_selected_style,
            "bullet": style.inline.bullet_unselected_style,
            "text.sel": style.inline.text_selected_style,
            "text": style.inline.text_unselected_style,
            "hint": style.inline.instruction_style,
        }
    )

    def _render() -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        fragments.append(("class:prefix", style.prompt.prefix))
        fragments.append(("class:prompt", f"{question.prompt} "))

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

        if style.inline.instruction:
            fragments.append(("", "  "))
            fragments.append(("class:hint", style.inline.instruction))

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

    app: Application[object] = Application(
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
    default_value: object,
    choices: Sequence[Choice] | None = None,
    value_to_label: ChoiceLabelMap | None = None,
    style: Style | None = None,
) -> object:
    style = style or Style()
    choices = list(choices or [])
    if not choices:
        return default_value

    mapping: ChoiceChoiceMap = dict(value_to_label) if value_to_label is not None else dict(choices)
    default_list = _fallback_default_values(question, default_value)
    _print_fallback_choices(question, choices, mapping, default_list, style)
    value_map, label_map, index_map = _fallback_lookup_maps(choices)

    while True:
        response = console.input(f"[bold green]{style.input_prefix} [/bold green]").strip()
        candidate = _resolve_fallback_choice(
            question,
            response,
            default_list,
            value_map,
            label_map,
            index_map,
            style,
        )
        if candidate is None:
            continue

        raw_value = response or (
            ", ".join(candidate) if isinstance(candidate, list) else str(candidate)
        )
        processed = _apply_parser(question, candidate, answers, raw=str(candidate))

        try:
            _run_validator(question, processed, answers, raw_value)
        except ValueError as error:
            _print_error(error, style)
        else:
            if question.multiselect:
                processed_list = _as_choice_values(processed)
                _print_choice_summary(question, processed_list, mapping, style)
                return processed_list

            _print_choice_summary(question, candidate, mapping, style)

            return processed


def _fallback_default_values(question: Question, default_value: object) -> list[str]:
    if question.multiselect and isinstance(default_value, (list, tuple, set)):
        return [str(item) for item in default_value]
    if not question.multiselect and default_value not in (None, "", []):
        return [str(default_value)]

    return []


def _print_fallback_choices(
    question: Question,
    choices: Sequence[Choice],
    mapping: ChoiceLabelMap,
    default_list: Sequence[str],
    style: Style,
) -> None:
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

    if default_list:
        console.print(
            Text(
                "  default: "
                + ", ".join(
                    _choice_label(value, mapping.get(value, value)) for value in default_list
                ),
                style=style.default_style,
            )
        )


def _fallback_lookup_maps(
    choices: Sequence[Choice],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    value_map = {value.lower(): value for value, _ in choices}
    label_map = {label.lower(): value for value, label in choices}
    index_map = {str(idx): value for idx, (value, _) in enumerate(choices, start=1)}

    return value_map, label_map, index_map


def _resolve_fallback_token(
    token: str,
    value_map: Mapping[str, str],
    label_map: Mapping[str, str],
    index_map: Mapping[str, str],
) -> str | None:
    lower = token.lower()
    if token in index_map:
        return index_map[token]
    if lower in value_map:
        return value_map[lower]

    return label_map.get(lower)


def _resolve_fallback_multiselect(
    response: str,
    value_map: Mapping[str, str],
    label_map: Mapping[str, str],
    index_map: Mapping[str, str],
    style: Style,
) -> list[str] | None:
    tokens = [token.strip() for token in response.split(",") if token.strip()]
    resolved: list[str] = []
    for token in tokens:
        value = _resolve_fallback_token(token, value_map, label_map, index_map)
        if value is None:
            _print_error(f"Unknown choice '{token}'.", style)
            return None

        resolved.append(value)

    return resolved


def _resolve_fallback_choice(
    question: Question,
    response: str,
    default_list: Sequence[str],
    value_map: Mapping[str, str],
    label_map: Mapping[str, str],
    index_map: Mapping[str, str],
    style: Style,
) -> str | list[str] | None:
    if not response:
        if question.multiselect:
            return list(default_list)

        if default_list:
            return default_list[0]

        _print_error("Please choose a value.", style)

        return None

    if question.multiselect:
        return _resolve_fallback_multiselect(response, value_map, label_map, index_map, style)

    resolved = _resolve_fallback_token(response, value_map, label_map, index_map)

    return resolved or response


def _as_choice_values(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]

    return [str(value)]


def _print_choice_summary(
    question: Question,
    value: object,
    value_to_label: ChoiceLabelMap,
    style: Style,
) -> None:
    if question.multiselect:
        items = _as_choice_values(value)
        labels = [_choice_label(item, value_to_label.get(item, item)) for item in items]
        summary = ", ".join(labels) if labels else "none"
        summary_style = style.summary.selected_style if labels else style.summary.dim_style
    else:
        text_value = str(value)
        summary = _choice_label(text_value, value_to_label.get(text_value, text_value))
        summary_style = style.summary.selected_style

    console.print(Text(f"{style.summary.prefix}{summary}", style=summary_style))


def _print_text_summary(value: object, style: Style) -> None:
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


def _populate_default_placeholder(buffer: Buffer, default_text: str) -> bool:
    if buffer.text:
        return False

    buffer.insert_text(default_text)

    return True


def _placeholder_move_left(buffer: Buffer, default_text: str) -> None:
    _populate_default_placeholder(buffer, default_text)

    if buffer.cursor_position > 0:
        buffer.cursor_left(count=1)


def _placeholder_move_right(buffer: Buffer, default_text: str) -> None:
    inserted = _populate_default_placeholder(buffer, default_text)
    if not inserted:
        buffer.cursor_right(count=1)


def _placeholder_move_home(buffer: Buffer, default_text: str) -> None:
    _populate_default_placeholder(buffer, default_text)

    buffer.cursor_position = 0


def _placeholder_move_end(buffer: Buffer, default_text: str) -> None:
    _populate_default_placeholder(buffer, default_text)

    buffer.cursor_position = len(buffer.text)


def _placeholder_backspace(buffer: Buffer, default_text: str) -> None:
    _populate_default_placeholder(buffer, default_text)

    if buffer.text:
        buffer.delete_before_cursor(count=1)


def _placeholder_delete(buffer: Buffer, default_text: str) -> None:
    _populate_default_placeholder(buffer, default_text)

    if buffer.text:
        buffer.delete(count=1)


def _bind_placeholder_action(
    keybind: KeyBindings,
    keys: Sequence[str],
    default_text: str,
    action: Callable[[Buffer, str], None],
) -> None:
    for key in keys:

        @keybind.add(key)
        def _handler(
            event: KeyPressEvent,
            _action: Callable[[Buffer, str], None] = action,
            _default_text: str = default_text,
        ) -> None:  # pragma: no cover - interactive
            _action(event.app.current_buffer, _default_text)


def _placeholder_key_bindings(default_text: str) -> KeyBindings:
    keybind = KeyBindings()
    _bind_placeholder_action(keybind, ("left",), default_text, _placeholder_move_left)
    _bind_placeholder_action(keybind, ("right",), default_text, _placeholder_move_right)
    _bind_placeholder_action(keybind, ("home",), default_text, _placeholder_move_home)
    _bind_placeholder_action(keybind, ("end",), default_text, _placeholder_move_end)
    _bind_placeholder_action(keybind, ("backspace", "c-h"), default_text, _placeholder_backspace)
    _bind_placeholder_action(keybind, ("delete", "c-d"), default_text, _placeholder_delete)
    _bind_interrupt_key(keybind)

    return keybind


def _apply_cli_answer(question: Question, value: object, answers: dict[str, Any]) -> object:
    raw_value = value

    if question.multiselect:
        if isinstance(value, (list, tuple, set)):
            values = [str(item) for item in value]
        else:
            values = [str(value)]

        raw_value = ", ".join(values)
    else:
        values = [str(value)]

    choices = question.resolve_choices(answers)
    if choices:
        allowed = {choice for choice, _label in choices}
        if question.multiselect:
            invalid = [item for item in values if item not in allowed]
            if invalid:
                raise ValueError(f"invalid choice(s): {', '.join(invalid)}")
        elif values[0] not in allowed:
            raise ValueError(f"invalid choice: {values[0]}")

    processed: object

    if question.multiselect:
        processed = values
    else:
        processed = _apply_parser(question, value, answers, raw=str(value))

    _run_validator(question, processed, answers, raw=str(raw_value))

    return processed


def _apply_parser(
    question: Question,
    value: object,
    answers: dict[str, Any],
    raw: str | None = None,
) -> object:
    if question.parser and not question.multiselect:
        raw_value = raw if raw is not None else str(value)
        return question.parser(raw_value, answers)

    return value


def _run_validator(
    question: Question,
    value: object,
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
    """Return whether both stdin and stdout are attached to a TTY."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _print_error(message: object, style: Style) -> None:
    console.print(f"[{style.error.style}]{style.error.label}[/] {message}")


__all__ = [
    "ask_question",
    "collect_answers",
    "confirm_overwrite",
    "console",
    "supports_live_interaction",
]
