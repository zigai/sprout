from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style as PTStyle
from rich.console import Console
from rich.control import Control
from rich.segment import ControlType
from rich.text import Text

from sprout.prompt.processing import AnswerProcessor, Choice, ResolvedPrompt
from sprout.prompt.question import DefaultValue, Question
from sprout.prompt.style import Style

if TYPE_CHECKING:
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.key_binding.key_processor import KeyPressEvent


console = Console()

type ChoiceLabelMap = Mapping[str, str | None]
type ChoiceChoiceMap = dict[str, str | None]


class TerminalQuestion:
    def __init__(self, question: Question, resolved: ResolvedPrompt, style: Style) -> None:
        self.question = question
        self.resolved = resolved
        self.style = style

    def print_header(self) -> None:
        header = Text()
        header.append(self.style.prompt.prefix, style=self.style.prompt.prefix_style)
        question_text = Text(self.question.prompt, style=self.style.prompt.text_style)
        question_text.stylize("bold")
        header += question_text

        if self.question.help:
            header.append(
                f" - {self.question.help}",
                style=self.style.prompt.help_style,
            )

        instruction = (
            self.style.menu.instruction_multi
            if self.question.multiselect
            else self.style.menu.instruction_single
        )
        if self.resolved.has_choices and instruction:
            header.append("  ")
            header.append(instruction, style=self.style.menu.instruction_style)

        inline_preview = self._format_inline_preview()
        if inline_preview:
            header.append(" ")
            header.append(inline_preview, style=self.style.default_style)

        console.print(header)

    def run_choice_application(
        self,
        choices: Sequence[Choice],
        default_value: DefaultValue,
    ) -> DefaultValue:
        items = list(choices)
        if not items:
            return default_value

        value_to_index = {value: idx for idx, (value, _) in enumerate(items)}
        selected_indices: set[int]

        if self.question.multiselect:
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
                "title": self.style.prompt.text_style,
                "hint": self.style.menu.instruction_style,
                "caret": self.style.menu.caret_style,
                "bullet.sel": self.style.menu.bullet_selected_style,
                "bullet": self.style.menu.bullet_unselected_style,
                "text.sel": self.style.menu.text_selected_style,
                "text": self.style.menu.text_unselected_style,
            }
        )

        def _render() -> list[tuple[str, str]]:
            fragments: list[tuple[str, str]] = []

            for idx, (value, label) in enumerate(items):
                caret = (
                    self.style.menu.caret_icon
                    if idx == pointer_box[0]
                    else " " * len(self.style.menu.caret_icon)
                )
                caret_style = "class:caret" if idx == pointer_box[0] else ""
                bullet_selected = (
                    idx in selected_box if self.question.multiselect else idx == pointer_box[0]
                )
                bullet_style = "class:bullet.sel" if bullet_selected else "class:bullet"
                bullet = (
                    self.style.menu.bullet_selected_icon
                    if bullet_selected
                    else self.style.menu.bullet_unselected_icon
                )
                text_style = "class:text.sel" if idx == pointer_box[0] else "class:text"
                display = label or value

                fragments.append((caret_style, caret))
                fragments.append((bullet_style, bullet))
                fragments.append((text_style, display))

                if idx != len(items) - 1:
                    fragments.append(("", "\n"))

            return fragments

        body_control = FormattedTextControl(_render)
        body = Window(content=body_control, always_hide_cursor=True)
        app: Application[object] = Application(
            layout=Layout(HSplit([body])),
            key_bindings=ChoiceKeyBindings(
                pointer_box=pointer_box,
                selected_box=selected_box,
                items=items,
                multiselect=self.question.multiselect,
            ).build(),
            mouse_support=False,
            full_screen=False,
            style=pt_style,
        )

        result = app.run()
        if result is None:
            if self.question.multiselect:
                return [items[idx][0] for idx in sorted(selected_indices)]

            return default_value

        return result

    def run_inline_application(self) -> DefaultValue:
        items = list(self.resolved.choices)
        value_to_index = {value: idx for idx, (value, _) in enumerate(items)}
        default_value = self.resolved.default_value
        pointer = value_to_index.get(default_value, 0) if isinstance(default_value, str) else 0
        pointer_box = [pointer]

        pt_style = PTStyle.from_dict(
            {
                "prompt": self.style.prompt.text_style,
                "prefix": self.style.prompt.prefix_style,
                "bullet.sel": self.style.inline.bullet_selected_style,
                "bullet": self.style.inline.bullet_unselected_style,
                "text.sel": self.style.inline.text_selected_style,
                "text": self.style.inline.text_unselected_style,
                "hint": self.style.inline.instruction_style,
            }
        )

        def _render() -> list[tuple[str, str]]:
            fragments: list[tuple[str, str]] = [
                ("class:prefix", self.style.prompt.prefix),
                ("class:prompt", f"{self.question.prompt} "),
            ]

            for idx, (value, label) in enumerate(items):
                selected = idx == pointer_box[0]
                bullet_style = "class:bullet.sel" if selected else "class:bullet"
                bullet = (
                    self.style.inline.selected_icon
                    if selected
                    else self.style.inline.unselected_icon
                )
                text_style = "class:text.sel" if selected else "class:text"
                display = label or value

                fragments.append((bullet_style, bullet))
                fragments.append(("", " "))
                fragments.append((text_style, display))

                if idx != len(items) - 1:
                    fragments.append(("", self.style.inline.separator))

            if self.style.inline.instruction:
                fragments.append(("", "  "))
                fragments.append(("class:hint", self.style.inline.instruction))

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

    def read_text_response(self, default_value: DefaultValue) -> str:
        if supports_live_interaction():
            session: PromptSession[str] = PromptSession()
            if default_value not in (None, "", []):
                default_text = str(default_value)
                return session.prompt(
                    f"{self.style.input_prefix} ",
                    placeholder=default_text,
                    key_bindings=placeholder_key_bindings(default_text),
                )

            return session.prompt(f"{self.style.input_prefix} ")

        return console.input(f"[bold green]{self.style.input_prefix} [/bold green]").strip()

    def _format_inline_preview(self) -> str:
        if not self.resolved.inline_choice_enabled or not self.resolved.choices:
            return ""

        parts: list[str] = []
        for value, label in self.resolved.choices:
            icon = (
                self.style.inline.selected_icon
                if value == self.resolved.default_value
                else self.style.inline.unselected_icon
            )
            parts.append(f"{icon} {label or value}")

        return self.style.inline.separator.join(parts)


@dataclass
class ChoiceKeyBindings:
    pointer_box: list[int]
    selected_box: set[int]
    items: Sequence[Choice]
    multiselect: bool
    keybind: KeyBindings = field(default_factory=KeyBindings, init=False)

    def build(self) -> KeyBindings:
        for key in ("up", "k", "left", "h"):
            self._bind_move_key(key, delta=-1)

        for key in ("down", "j", "right", "l"):
            self._bind_move_key(key, delta=1)

        self._bind_move_key("home", position=0)
        self._bind_move_key("end", position=-1)

        if self.multiselect:
            self._bind_toggle_key()

        self._bind_confirm_key()
        self._bind_interrupt_key()

        return self.keybind

    def _bind_move_key(
        self,
        key: str,
        *,
        delta: int | None = None,
        position: int | None = None,
    ) -> None:
        item_count = len(self.items)

        @self.keybind.add(key)
        def _move(
            event: KeyPressEvent,
            _delta: int | None = delta,
            _position: int | None = position,
        ) -> None:  # pragma: no cover - interactive
            if _position is None:
                self.pointer_box[0] = (self.pointer_box[0] + (_delta or 0)) % item_count
            elif _position < 0:
                self.pointer_box[0] = item_count - 1
            else:
                self.pointer_box[0] = _position

            event.app.invalidate()

    def _bind_toggle_key(self) -> None:
        @self.keybind.add(" ")
        def _toggle(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
            idx = self.pointer_box[0]
            if idx in self.selected_box:
                self.selected_box.remove(idx)
            else:
                self.selected_box.add(idx)

            event.app.invalidate()

    def _bind_confirm_key(self) -> None:
        @self.keybind.add("enter")
        def _confirm(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
            if self.multiselect:
                result: str | list[str] = [self.items[idx][0] for idx in sorted(self.selected_box)]
            else:
                result = self.items[self.pointer_box[0]][0]

            event.app.exit(result=result)

    def _bind_interrupt_key(self) -> None:
        @self.keybind.add("c-c")
        def _interrupt(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
            event.app.exit(exception=KeyboardInterrupt)


def _bind_interrupt_key(keybind: KeyBindings) -> None:
    @keybind.add("c-c")
    def _interrupt(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        event.app.exit(exception=KeyboardInterrupt)


class FallbackChoicePrompt:
    def __init__(
        self,
        *,
        question: Question,
        answers: dict[str, DefaultValue],
        default_value: DefaultValue,
        choices: Sequence[Choice],
        value_to_label: ChoiceLabelMap | None = None,
        style: Style | None = None,
    ) -> None:
        self.question = question
        self.answers = answers
        self.default_value = default_value
        self.choices = list(choices)
        self.style = style or Style()
        self.mapping: ChoiceChoiceMap = (
            dict(value_to_label) if value_to_label is not None else dict(self.choices)
        )
        self.default_list = fallback_default_values(question, default_value)
        self.value_map, self.label_map, self.index_map = fallback_lookup_maps(self.choices)
        self.processor = AnswerProcessor(question, answers)

    def ask(self) -> DefaultValue:
        if not self.choices:
            return self.default_value

        print_fallback_choices(
            self.question,
            self.choices,
            self.mapping,
            self.default_list,
            self.style,
        )

        while True:
            response = console.input(f"[bold green]{self.style.input_prefix} [/bold green]").strip()
            candidate = self.resolve_choice(response)
            if candidate is None:
                continue

            raw_value = self._raw_value(response, candidate)

            try:
                processed = self.processor.process(
                    candidate,
                    raw=str(candidate),
                    validator_raw=raw_value,
                )
            except ValueError as e:
                print_error(e, self.style)
            else:
                return self._summarize_and_return(candidate, processed)

    def resolve_choice(self, response: str) -> str | list[str] | None:
        if not response:
            if self.question.multiselect:
                return list(self.default_list)

            if self.default_list:
                return self.default_list[0]

            print_error("Please choose a value.", self.style)

            return None

        if self.question.multiselect:
            return self._resolve_multiselect(response)

        resolved = self._resolve_token(response)

        return resolved or response

    def _raw_value(self, response: str, candidate: str | list[str]) -> str:
        if response:
            return response
        if isinstance(candidate, list):
            return ", ".join(candidate)

        return candidate

    def _summarize_and_return(
        self, candidate: str | list[str], processed: DefaultValue
    ) -> DefaultValue:
        if self.question.multiselect:
            processed_list = as_choice_values(processed)
            print_choice_summary(self.question, processed_list, self.mapping, self.style)
            return processed_list

        print_choice_summary(self.question, candidate, self.mapping, self.style)

        return processed

    def _resolve_multiselect(self, response: str) -> list[str] | None:
        tokens = [token.strip() for token in response.split(",") if token.strip()]
        resolved: list[str] = []
        for token in tokens:
            value = self._resolve_token(token)
            if value is None:
                print_error(f"Unknown choice '{token}'.", self.style)
                return None

            resolved.append(value)

        return resolved

    def _resolve_token(self, token: str) -> str | None:
        lower = token.lower()
        if token in self.index_map:
            return self.index_map[token]
        if lower in self.value_map:
            return self.value_map[lower]

        return self.label_map.get(lower)


def fallback_default_values(question: Question, default_value: DefaultValue) -> list[str]:
    if question.multiselect and isinstance(default_value, (list, tuple, set)):
        return [str(item) for item in default_value]
    if not question.multiselect and default_value not in (None, "", []):
        return [str(default_value)]

    return []


def print_fallback_choices(
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


def fallback_lookup_maps(
    choices: Sequence[Choice],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    value_map = {value.lower(): value for value, _ in choices}
    label_map = {label.lower(): value for value, label in choices}
    index_map = {str(idx): value for idx, (value, _) in enumerate(choices, start=1)}

    return value_map, label_map, index_map


def as_choice_values(value: DefaultValue) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]

    return [str(value)]


def print_choice_summary(
    question: Question,
    value: DefaultValue,
    value_to_label: ChoiceLabelMap,
    style: Style,
) -> None:
    if question.multiselect:
        items = as_choice_values(value)
        labels = [_choice_label(item, value_to_label.get(item, item)) for item in items]
        summary = ", ".join(labels) if labels else "none"
        summary_style = style.summary.selected_style if labels else style.summary.dim_style
    else:
        text_value = str(value)
        summary = _choice_label(text_value, value_to_label.get(text_value, text_value))
        summary_style = style.summary.selected_style

    console.print(Text(f"{style.summary.prefix}{summary}", style=summary_style))


def print_text_summary(value: str, style: Style) -> None:
    console.print(Text(f"{style.summary.prefix}{value}", style=style.summary.selected_style))


def highlight_prompt_line(value: str, style: Style) -> None:
    styled = Text(f"{style.input_prefix} {value}", style=style.summary.selected_style)
    controls = (
        Control((ControlType.CURSOR_UP, 1)),
        Control(ControlType.CARRIAGE_RETURN),
        Control((ControlType.ERASE_IN_LINE, 2)),
    )
    console.control(*controls)
    console.print(styled)


@dataclass
class DefaultPlaceholderBindings:
    default_text: str
    keybind: KeyBindings = field(default_factory=KeyBindings, init=False)

    def build(self) -> KeyBindings:
        self._bind_action(("left",), self._move_left)
        self._bind_action(("right",), self._move_right)
        self._bind_action(("home",), self._move_home)
        self._bind_action(("end",), self._move_end)
        self._bind_action(("backspace", "c-h"), self._backspace)
        self._bind_action(("delete", "c-d"), self._delete)
        _bind_interrupt_key(self.keybind)

        return self.keybind

    def _populate_default(self, buffer: Buffer) -> bool:
        if buffer.text:
            return False

        buffer.insert_text(self.default_text)

        return True

    def _move_left(self, buffer: Buffer) -> None:
        self._populate_default(buffer)

        if buffer.cursor_position > 0:
            buffer.cursor_left(count=1)

    def _move_right(self, buffer: Buffer) -> None:
        inserted = self._populate_default(buffer)
        if not inserted:
            buffer.cursor_right(count=1)

    def _move_home(self, buffer: Buffer) -> None:
        self._populate_default(buffer)

        buffer.cursor_position = 0

    def _move_end(self, buffer: Buffer) -> None:
        self._populate_default(buffer)

        buffer.cursor_position = len(buffer.text)

    def _backspace(self, buffer: Buffer) -> None:
        self._populate_default(buffer)

        if buffer.text:
            buffer.delete_before_cursor(count=1)

    def _delete(self, buffer: Buffer) -> None:
        self._populate_default(buffer)

        if buffer.text:
            buffer.delete(count=1)

    def _bind_action(
        self,
        keys: Sequence[str],
        action: Callable[[Buffer], None],
    ) -> None:
        for key in keys:

            @self.keybind.add(key)
            def _handler(
                event: KeyPressEvent,
                _action: Callable[[Buffer], None] = action,
            ) -> None:  # pragma: no cover - interactive
                _action(event.app.current_buffer)


def placeholder_key_bindings(default_text: str) -> KeyBindings:
    return DefaultPlaceholderBindings(default_text).build()


def _choice_label(value: str, label: str | None) -> str:
    return label or value


def supports_live_interaction() -> bool:
    """Return whether both stdin and stdout are attached to a TTY."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def print_error(message: str | BaseException, style: Style) -> None:
    console.print(f"[{style.error.style}]{style.error.label}[/] {message}")


__all__ = [
    "FallbackChoicePrompt",
    "TerminalQuestion",
    "console",
    "highlight_prompt_line",
    "print_choice_summary",
    "print_error",
    "print_text_summary",
    "supports_live_interaction",
]
