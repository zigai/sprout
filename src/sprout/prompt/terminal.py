from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.layout import Layout as PTLayout
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.processors import AfterInput, BeforeInput
from prompt_toolkit.styles import Style as PTStyle
from rich.cells import cell_len
from rich.color import Color, ColorType
from rich.console import Console
from rich.style import Style as RichStyle
from rich.text import Text
from rich.theme import Theme

from sprout.prompt.layout import CURSOR_ROLE, Fragments, Layout, MenuState, PromptView
from sprout.prompt.processing import AnswerProcessor, Choice
from sprout.prompt.question import DefaultValue, Question
from sprout.prompt.style import Palette

if TYPE_CHECKING:
    from prompt_toolkit.formatted_text import StyleAndTextTuples
    from prompt_toolkit.key_binding.key_processor import KeyPressEvent

DEFAULT_THEME = Theme(
    {
        "repr.path": "bright_blue",
        "repr.filename": "bright_blue",
        "repr.url": "underline bright_blue",
        "markdown.link": "bright_blue",
        "markdown.link_url": "underline bright_blue",
    }
)

console = Console(theme=DEFAULT_THEME)
type ChoiceLabelMap = Mapping[str, str | None]

ANSI_COLOR_NAMES = (
    "ansiblack",
    "ansired",
    "ansigreen",
    "ansiyellow",
    "ansiblue",
    "ansimagenta",
    "ansicyan",
    "ansigray",
    "ansibrightblack",
    "ansibrightred",
    "ansibrightgreen",
    "ansibrightyellow",
    "ansibrightblue",
    "ansibrightmagenta",
    "ansibrightcyan",
    "ansiwhite",
)
TEXT_ATTRIBUTES = ("bold", "dim", "italic", "underline", "blink", "reverse", "strike")


def _prompt_toolkit_color(color: Color) -> str | None:
    if color.type is ColorType.DEFAULT:
        return None
    if color.type is ColorType.STANDARD and color.number is not None:
        return ANSI_COLOR_NAMES[color.number]

    return color.get_truecolor().hex


def prompt_toolkit_style_string(rich_style: str) -> str:
    """Convert a Rich style string into the equivalent prompt_toolkit style string."""
    parsed = RichStyle.parse(rich_style)
    parts = [attribute for attribute in TEXT_ATTRIBUTES if getattr(parsed, attribute)]
    if parsed.color is not None and (color := _prompt_toolkit_color(parsed.color)):
        parts.append(color)

    if parsed.bgcolor is not None and (color := _prompt_toolkit_color(parsed.bgcolor)):
        parts.append(f"bg:{color}")

    return " ".join(parts)


def prompt_toolkit_style(palette: Palette) -> PTStyle:
    return PTStyle.from_dict(
        {
            role.name: prompt_toolkit_style_string(getattr(palette, role.name))
            for role in fields(palette)
        }
    )


def _live_style(role: str) -> str:
    if role in ("", CURSOR_ROLE):
        return role

    return f"class:{role}"


def _live_fragments(fragments: Fragments) -> StyleAndTextTuples:
    return [(_live_style(role), text) for role, text in fragments]


def rich_text(fragments: Fragments, palette: Palette) -> Text:
    return Text.assemble(
        *[
            (text, getattr(palette, role) if role else "")
            for role, text in fragments
            if role != CURSOR_ROLE
        ]
    )


def print_fragments(fragments: Fragments, layout: Layout) -> None:
    if fragments:
        console.print(rich_text(fragments, layout.palette))


def rendered_height(fragments: Fragments, columns: int) -> int:
    """Return how many terminal rows the fragments take, counting wrapped lines."""
    text = "".join(part for _role, part in fragments)
    return sum(max(1, -(-cell_len(line) // columns)) for line in text.split("\n"))


def _app_width() -> int:
    return get_app().output.get_size().columns


def _text_window(render: Callable[[], Fragments]) -> Window:
    return Window(
        FormattedTextControl(lambda: _live_fragments(render())),
        always_hide_cursor=True,
        wrap_lines=True,
        dont_extend_height=True,
    )


def _cursor_window(render: Callable[[], Fragments]) -> Window:
    """Show the terminal cursor where the rendered fragments place `CURSOR_ROLE`, if anywhere."""
    has_cursor = [False]

    def fragments() -> StyleAndTextTuples:
        rendered = render()
        has_cursor[0] = any(role == CURSOR_ROLE for role, _text in rendered)
        return _live_fragments(rendered)

    return Window(
        FormattedTextControl(fragments, focusable=True),
        always_hide_cursor=Condition(lambda: not has_cursor[0]),
        wrap_lines=True,
        dont_extend_height=True,
    )


class TerminalQuestion:
    def __init__(self, view: PromptView, layout: Layout) -> None:
        self.view = view
        self.layout = layout

    def print_header(self) -> None:
        print_fragments(self.layout.header(self.view, console.width), self.layout)

    def read_fallback_text(self) -> str:
        prefix = [*self.layout.input_prefix(self.view), ("accent", "› ")]  # noqa: RUF001
        return console.input(rich_text(prefix, self.layout.palette))

    def run_text_application(self, initial: str = "") -> str:
        view = self.view
        buffer = Buffer(multiline=False)
        buffer.text = initial
        buffer.cursor_position = len(initial)

        keybind = KeyBindings()

        @keybind.add("enter")
        def _submit(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
            event.app.exit(result=buffer.text)

        bindings = (
            placeholder_key_bindings(view.placeholder)
            if view.placeholder
            else _interrupt_bindings()
        )
        input_window = Window(
            BufferControl(
                buffer,
                input_processors=[
                    BeforeInput(lambda: _live_fragments(self.layout.input_prefix(view))),
                    AfterInput(lambda: [] if buffer.text else [("class:muted", view.placeholder)]),
                ],
            ),
            dont_extend_height=True,
        )
        app: Application[str] = Application(
            layout=PTLayout(
                HSplit(
                    [
                        _text_window(lambda: self.layout.header(view, _app_width())),
                        input_window,
                        _text_window(lambda: self.layout.text_footer(view, _app_width())),
                    ]
                ),
                focused_element=input_window,
            ),
            key_bindings=merge_key_bindings([keybind, bindings]),
            cursor=CursorShape.BEAM,
            mouse_support=False,
            full_screen=False,
            style=prompt_toolkit_style(self.layout.palette),
            erase_when_done=True,
        )

        return app.run()

    def run_menu_application(self, default_value: DefaultValue) -> DefaultValue:
        view = self.view
        lists = self.layout.lists
        values = [value for value, _label in view.choices]
        state = MenuState(choices=view.choices)
        if view.kind == "multiselect":
            defaults = default_value if isinstance(default_value, (list, tuple, set)) else []
            state.selected = {values.index(value) for value in defaults if value in values}
            state.pointer = min(state.selected, default=0)
        elif isinstance(default_value, str) and default_value in values:
            state.pointer = values.index(default_value)

        def render() -> Fragments:
            size = get_app().output.get_size()
            state.resize(lists.max_visible)
            while True:
                fragments = self.layout.menu(view, state, size.columns)
                overflow = rendered_height(fragments, size.columns) - (size.rows - 1)
                if overflow <= 0 or state.visible == 1:
                    return fragments

                state.resize(max(1, state.visible - overflow))

        app: Application[DefaultValue] = Application(
            layout=PTLayout(HSplit([_cursor_window(render)])),
            key_bindings=ChoiceKeyBindings(
                state=state,
                multiselect=view.kind == "multiselect",
                search=lists.search and view.kind != "confirm",
            ).build(),
            cursor=CursorShape.BEAM,
            mouse_support=False,
            full_screen=False,
            style=prompt_toolkit_style(self.layout.palette),
            erase_when_done=True,
        )

        return app.run()


@dataclass
class ChoiceKeyBindings:
    state: MenuState
    multiselect: bool
    search: bool
    keybind: KeyBindings = field(default_factory=KeyBindings, init=False)

    def build(self) -> KeyBindings:
        for key in ("up", "left", "s-tab"):
            self._bind(key, lambda: self.state.move(-1))

        for key in ("down", "right", "tab"):
            self._bind(key, lambda: self.state.move(1))

        self._bind("pageup", lambda: self.state.move(-self.state.visible, wrap=False))
        self._bind("pagedown", lambda: self.state.move(self.state.visible, wrap=False))
        self._bind("home", lambda: self.state.jump(last=False))
        self._bind("end", lambda: self.state.jump(last=True))

        if self.multiselect:
            self._bind(" ", self._toggle)
            self._bind("c-a", self._toggle_all)

        if self.search:
            self._bind_search_keys()

        self._bind_confirm_key()
        _bind_interrupt_key(self.keybind)

        return self.keybind

    def _bind(self, key: str, action: Callable[[], None]) -> None:
        @self.keybind.add(key)
        def _handler(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
            action()
            event.app.invalidate()

    def _toggle(self) -> None:
        current = self.state.current()
        if current is not None:
            self.state.selected ^= {current}

    def _toggle_all(self) -> None:
        matches = set(self.state.matches())
        if matches <= self.state.selected:
            self.state.selected -= matches
        else:
            self.state.selected |= matches

    def _bind_search_keys(self) -> None:
        @self.keybind.add("<any>")
        def _type(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
            typed = "".join(char for char in event.data if char.isprintable())
            if self.multiselect:
                typed = typed.replace(" ", "")

            if typed:
                self.state.search(self.state.query + typed)
                event.app.invalidate()

        self._bind("backspace", lambda: self.state.search(self.state.query[:-1]))
        self._bind("c-u", lambda: self.state.search(""))
        self._bind("escape", lambda: self.state.search(""))

    def _bind_confirm_key(self) -> None:
        @self.keybind.add("enter")
        def _confirm(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
            choices = self.state.choices
            if self.multiselect:
                event.app.exit(result=[choices[idx][0] for idx in sorted(self.state.selected)])
                return

            current = self.state.current()
            if current is not None:
                event.app.exit(result=choices[current][0])


def _bind_interrupt_key(keybind: KeyBindings) -> None:
    @keybind.add("c-c")
    def _interrupt(event: KeyPressEvent) -> None:  # pragma: no cover - interactive
        event.app.exit(exception=KeyboardInterrupt)


def _interrupt_bindings() -> KeyBindings:
    keybind = KeyBindings()
    _bind_interrupt_key(keybind)
    return keybind


class FallbackChoicePrompt:
    def __init__(
        self,
        *,
        question: Question,
        answers: dict[str, DefaultValue],
        default_value: DefaultValue,
        choices: Sequence[Choice],
        layout: Layout,
    ) -> None:
        self.question = question
        self.answers = answers
        self.default_value = default_value
        self.choices = list(choices)
        self.layout = layout
        self.labels: ChoiceLabelMap = dict(self.choices)
        self.default_list = fallback_default_values(question, default_value)
        self.value_map, self.label_map, self.index_map = fallback_lookup_maps(self.choices)
        self.processor = AnswerProcessor(question, answers)

    def ask(self) -> DefaultValue:
        if not self.choices:
            return self.default_value

        print_fallback_choices(
            self.question,
            self.choices,
            self.labels,
            self.default_list,
            self.layout,
        )

        while True:
            prompt = rich_text([("accent", "› ")], self.layout.palette)  # noqa: RUF001
            response = console.input(prompt).strip()
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
                print_error(e, self.layout)
            else:
                return self._summarize_and_return(candidate, processed)

    def resolve_choice(self, response: str) -> str | list[str] | None:
        if not response:
            allowed = {value for value, _label in self.choices}
            if any(value not in allowed for value in self.default_list):
                print_error("Default is not an available choice.", self.layout)
                return None

            if self.question.multiselect:
                return list(self.default_list)

            if self.default_list:
                return self.default_list[0]

            print_error("Please choose a value.", self.layout)

            return None

        if self.question.multiselect:
            return self._resolve_multiselect(response)

        resolved = self._resolve_token(response)
        if resolved is None:
            print_error(f"Unknown choice '{response}'.", self.layout)

        return resolved

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
            print_answer(
                self.question,
                choice_summary(self.question, processed_list, self.labels),
                self.layout,
            )
            return processed_list

        print_answer(
            self.question, choice_summary(self.question, candidate, self.labels), self.layout
        )

        return processed

    def _resolve_multiselect(self, response: str) -> list[str] | None:
        tokens = [token.strip() for token in response.split(",") if token.strip()]
        resolved: list[str] = []
        for token in tokens:
            value = self._resolve_token(token)
            if value is None:
                print_error(f"Unknown choice '{token}'.", self.layout)
                return None

            resolved.append(value)

        return resolved

    def _resolve_token(self, token: str) -> str | None:
        if token in self.index_map:
            return self.index_map[token]
        if any(token == value for value, _label in self.choices):
            return token

        matches = {value for value, label in self.choices if token == label}
        if len(matches) == 1:
            return matches.pop()
        if matches:
            return None

        lower = token.lower()
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
    layout: Layout,
) -> None:
    for idx, (value, label) in enumerate(choices, start=1):
        print_fragments([("muted", f"  {idx}) "), ("option", _choice_label(value, label))], layout)

    if question.multiselect:
        print_fragments([("muted", "  Enter comma-separated numbers or values")], layout)

    if default_list:
        labels = ", ".join(
            _choice_label(value, mapping.get(value, value)) for value in default_list
        )
        print_fragments([("muted", f"  default: {labels}")], layout)


def fallback_lookup_maps(
    choices: Sequence[Choice],
) -> tuple[dict[str, str | None], dict[str, str | None], dict[str, str]]:
    value_map: dict[str, str | None] = {}
    label_map: dict[str, str | None] = {}
    for value, label in choices:
        for key, mapping in ((value.lower(), value_map), (label.lower(), label_map)):
            mapping[key] = value if key not in mapping or mapping[key] == value else None

    index_map = {str(idx): value for idx, (value, _) in enumerate(choices, start=1)}

    return value_map, label_map, index_map


def as_choice_values(value: DefaultValue) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]

    return [str(value)]


def choice_summary(question: Question, value: DefaultValue, value_to_label: ChoiceLabelMap) -> str:
    if question.multiselect:
        items = as_choice_values(value)
        labels = [_choice_label(item, value_to_label.get(item, item)) for item in items]
        return ", ".join(labels) if labels else "none"

    text_value = str(value)

    return _choice_label(text_value, value_to_label.get(text_value, text_value))


def print_answer(question: Question, display: str, layout: Layout) -> None:
    print_fragments(layout.answered(question, display), layout)


@dataclass
class DefaultPlaceholderBindings:
    default_text: str
    keybind: KeyBindings = field(default_factory=KeyBindings, init=False)

    def build(self) -> KeyBindings:
        self._bind_action(("tab",), self._fill)
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

    def _fill(self, buffer: Buffer) -> None:
        self._populate_default(buffer)

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


def print_error(message: str | BaseException, layout: Layout) -> None:
    print_fragments(layout.error_line(str(message)), layout)


__all__ = [
    "DEFAULT_THEME",
    "FallbackChoicePrompt",
    "TerminalQuestion",
    "choice_summary",
    "console",
    "print_answer",
    "print_error",
    "print_fragments",
    "prompt_toolkit_style_string",
    "supports_live_interaction",
]
