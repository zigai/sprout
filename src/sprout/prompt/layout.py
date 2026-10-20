from __future__ import annotations

import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from rich.cells import cell_len, set_cell_size

from sprout.display import shorten_home
from sprout.prompt.processing import Choice
from sprout.prompt.question import Question
from sprout.prompt.style import (
    CompactStyle,
    Hints,
    KeyHint,
    ListOptions,
    Palette,
    RailStyle,
    Style,
)

type PromptKind = Literal["text", "confirm", "select", "multiselect"]
type Fragment = tuple[str, str]
type Fragments = list[Fragment]

CURSOR_ROLE = "[SetCursorPosition]"


@dataclass(frozen=True)
class Step:
    index: int
    total: int


@dataclass
class PromptView:
    question: Question
    kind: PromptKind
    choices: list[Choice]
    placeholder: str = ""
    step: Step | None = None
    error: str | None = None


@dataclass
class MenuState:
    """
    Cursor, selection, search query, and scroll position of one live option list.

    `pointer`, `selected`, and the returned indices refer to positions in `choices`, so a
    selection survives while a search hides it.
    """

    choices: list[Choice]
    pointer: int = 0
    selected: set[int] = field(default_factory=set)
    query: str = ""
    offset: int = 0
    visible: int = 8

    def matches(self) -> list[int]:
        terms = self.query.lower().split()
        return [
            index
            for index, (value, label) in enumerate(self.choices)
            if all(term in f"{label} {value}".lower() for term in terms)
        ]

    def move(self, delta: int, *, wrap: bool = True) -> None:
        matches = self.matches()
        if not matches:
            return

        position = self._position(matches)
        if wrap:
            position = (position + delta) % len(matches)
        else:
            position = max(0, min(len(matches) - 1, position + delta))

        self.pointer = matches[position]
        self._follow_pointer(matches)

    def jump(self, *, last: bool) -> None:
        matches = self.matches()
        if matches:
            self.pointer = matches[-1] if last else matches[0]
            self._follow_pointer(matches)

    def search(self, query: str) -> None:
        self.query = query
        self.offset = 0
        matches = self.matches()
        if matches and (query or self.pointer not in matches):
            self.pointer = matches[0]

        self._follow_pointer(matches)

    def resize(self, visible: int) -> None:
        self.visible = visible
        self._follow_pointer(self.matches())

    def current(self) -> int | None:
        return self.pointer if self.pointer in self.matches() else None

    def window(self) -> tuple[list[int], int, int]:
        """Return the visible indices and how many matches are hidden above and below."""
        matches = self.matches()
        end = self.offset + self.visible

        return matches[self.offset : end], self.offset, max(0, len(matches) - end)

    def _position(self, matches: list[int]) -> int:
        return matches.index(self.pointer) if self.pointer in matches else 0

    def _follow_pointer(self, matches: list[int]) -> None:
        position = self._position(matches)
        if position < self.offset:
            self.offset = position
        elif position >= self.offset + self.visible:
            self.offset = position - self.visible + 1

        self.offset = max(0, min(self.offset, len(matches) - self.visible))

    @property
    def scrolls(self) -> bool:
        return len(self.choices) > self.visible


class Layout(Protocol):
    @property
    def palette(self) -> Palette: ...
    @property
    def lists(self) -> ListOptions: ...

    def start(self, title: str | None) -> Fragments: ...
    def finish(self) -> Fragments: ...
    def header(self, view: PromptView, width: int) -> Fragments: ...
    def input_prefix(self, view: PromptView) -> Fragments: ...
    def text_footer(self, view: PromptView, width: int) -> Fragments: ...
    def menu(self, view: PromptView, state: MenuState, width: int) -> Fragments: ...
    def confirm_width(self, choices: Sequence[Choice]) -> int: ...
    def answered(self, question: Question, display: str) -> Fragments: ...
    def error_line(self, message: str) -> Fragments: ...


def fragments_width(fragments: Fragments) -> int:
    return sum(cell_len(text) for _role, text in fragments)


def join_lines(lines: Sequence[Fragments], separator: Fragment = ("", "\n")) -> Fragments:
    fragments: Fragments = []
    for index, line in enumerate(lines):
        if index:
            fragments.append(separator)

        fragments += line

    return fragments


def hint_fragments(hints: Hints, view: PromptView) -> Fragments:
    if not hints.show:
        return []

    keys: tuple[KeyHint, ...] = {
        "text": hints.text + (hints.text_default if view.placeholder else ()),
        "confirm": hints.confirm,
        "select": hints.select,
        "multiselect": hints.multiselect,
    }[view.kind]

    return join_lines(
        [[("key", f" {key} "), ("muted", f" {action}")] for key, action in keys],
        ("", "   "),
    )


def wrapped(text: str, role: str, prefix: Fragments, width: int) -> Fragments:
    lines = textwrap.wrap(text, max(10, width - fragments_width(prefix)))
    return join_lines([[*prefix, (role, line)] for line in lines])


def list_fragments(
    lists: ListOptions,
    state: MenuState,
    prefix: Fragments,
    row: Callable[[int], Fragments],
) -> Fragments:
    """Render the search line, scroll markers, and visible rows, one line each."""
    lines: list[Fragments] = []
    if lists.search and (state.query or state.scrolls):
        query: Fragments = (
            # prompt_toolkit can place the cursor only on a drawn cell, so it needs a trailing space.
            [("answer", state.query), (CURSOR_ROLE, ""), ("", " ")]
            if state.query
            else [(CURSOR_ROLE, ""), ("muted", lists.search_placeholder)]
        )
        lines.append([*prefix, ("muted", f"{lists.search_prefix} "), *query])

    rows, above, below = state.window()
    if state.scrolls:
        marker = lists.more_above.format(count=above) if above else ""
        lines.append([*prefix, ("muted", marker)])

    if not rows:
        lines.append([*prefix, ("muted", lists.no_matches)])

    lines += [row(index) for index in rows]
    if state.scrolls:
        marker = lists.more_below.format(count=below) if below else ""
        lines.append([*prefix, ("muted", marker)])

    return join_lines(lines)


def _option_width(choices: Sequence[Choice]) -> int:
    return max((cell_len(label or value) for value, label in choices), default=0)


class CompactLayout:
    def __init__(self, style: CompactStyle, label_width: int) -> None:
        self.style = style
        self.label_width = min(label_width, style.max_label_width)
        self.indent = " " * (cell_len(style.symbols.active) + 4)

    @property
    def palette(self) -> Palette:
        return self.style.palette

    @property
    def lists(self) -> ListOptions:
        return self.style.lists

    def start(self, title: str | None) -> Fragments:
        parts: Fragments = []
        if self.style.brand:
            parts.append(("brand", self.style.brand))

        if self.style.brand and title:
            parts.append(("muted", "  /  "))

        if title:
            parts.append(("muted", shorten_home(title)))

        if not parts:
            return []

        return [("", "\n  "), *parts, ("", "\n")]

    def finish(self) -> Fragments:
        return []

    def header(self, view: PromptView, width: int) -> Fragments:
        marker = (
            ("error", self.style.symbols.error)
            if view.error
            else ("accent", self.style.symbols.active)
        )
        fragments: Fragments = [("", "  "), marker, ("", "  "), ("title", view.question.prompt)]
        if view.step and self.style.show_progress:
            counter = f"{view.step.index}/{view.step.total}"
            gap = self._width(width) - fragments_width(fragments) - cell_len(counter)
            fragments += [("", " " * max(2, gap)), ("muted", counter)]

        if view.question.help:
            help_lines = wrapped(
                view.question.help, "muted", [("", self.indent)], self._width(width)
            )
            fragments += [("", "\n"), *help_lines]

        return fragments

    def input_prefix(self, view: PromptView) -> Fragments:
        del view
        return [("", self.indent)]

    def text_footer(self, view: PromptView, width: int) -> Fragments:
        rule_width = max(1, self._width(width) - len(self.indent))
        rule = self.style.symbols.rule * (rule_width // max(1, cell_len(self.style.symbols.rule)))
        fragments: Fragments = [("", self.indent), ("error" if view.error else "accent", rule)]

        return fragments + self._error(view) + self._hints(view)

    def menu(self, view: PromptView, state: MenuState, width: int) -> Fragments:
        fragments = [*self.header(view, width), ("", "\n\n")]
        if view.kind == "confirm":
            row = self._confirm_row(view.choices, state.pointer)
            return fragments + row + self._error(view) + self._hints(view)

        symbols = self.style.symbols
        mark_width = max(cell_len(symbols.checked), cell_len(symbols.unchecked))
        option_width = _option_width(view.choices) + 1
        current = state.current()

        def option(index: int) -> Fragments:
            value, label = view.choices[index]
            focused = index == current
            role = "highlight" if focused else "option"
            fragments: Fragments = [("", self.indent[:-2]), (role, "  ")]
            if view.kind == "multiselect":
                checked = index in state.selected
                mark = symbols.checked if checked else symbols.unchecked
                mark_role = "success" if checked else "muted"
                fragments.append((role if focused else mark_role, mark.ljust(mark_width) + " "))

                if checked and not focused:
                    role = "answer"

            return [*fragments, (role, (label or value).ljust(option_width))]

        rows = list_fragments(self.style.lists, state, [("", self.indent)], option)

        return fragments + rows + self._error(view) + self._hints(view)

    def confirm_width(self, choices: Sequence[Choice]) -> int:
        return fragments_width(self._confirm_row(choices, 0))

    def answered(self, question: Question, display: str) -> Fragments:
        label = question.prompt
        if cell_len(label) > self.label_width:
            label = set_cell_size(label, self.label_width - 1).rstrip() + "…"
        pad = self.label_width + 2 - cell_len(label)

        return [
            ("", "  "),
            ("success", self.style.symbols.done),
            ("", "  "),
            ("muted", label),
            ("", " " * pad),
            ("answer", display),
        ]

    def error_line(self, message: str) -> Fragments:
        return [("", self.indent), ("error", f"{self.style.symbols.error} {message}")]

    def _confirm_row(self, choices: Sequence[Choice], pointer: int) -> Fragments:
        buttons = [
            [("highlight" if index == pointer else "muted", f" {label or value} ")]
            for index, (value, label) in enumerate(choices)
        ]
        return [("", self.indent), *join_lines(buttons, ("", " "))]

    def _width(self, width: int) -> int:
        return min(width - 2, self.style.max_width)

    def _error(self, view: PromptView) -> Fragments:
        if not view.error:
            return []

        return [("", "\n"), *self.error_line(view.error)]

    def _hints(self, view: PromptView) -> Fragments:
        hints = hint_fragments(self.style.hints, view)
        if not hints:
            return []

        return [("", f"\n\n{self.indent}"), *hints]


class RailLayout:
    def __init__(self, style: RailStyle) -> None:
        self.style = style
        self.gap = "  "

    @property
    def palette(self) -> Palette:
        return self.style.palette

    @property
    def lists(self) -> ListOptions:
        return self.style.lists

    def start(self, title: str | None) -> Fragments:
        fragments: Fragments = [("muted", self.style.symbols.start)]
        if self.style.brand:
            fragments += [("", self.gap), ("brand", f" {self.style.brand} ")]

        if title:
            fragments += [("", self.gap), ("muted", shorten_home(title))]

        return fragments

    def finish(self) -> Fragments:
        symbols = self.style.symbols
        return [("muted", f"{symbols.line}\n{symbols.end}")]

    def header(self, view: PromptView, width: int) -> Fragments:
        symbols = self.style.symbols
        tone = self._tone(view)
        marker = symbols.error if view.error else symbols.active
        fragments: Fragments = [
            ("muted", f"{symbols.line}\n"),
            (tone, marker),
            ("", self.gap),
            ("title", view.question.prompt),
        ]
        if view.question.help:
            help_lines = wrapped(view.question.help, "muted", self._rail(tone), width)
            fragments += [("", "\n"), *help_lines]

        return fragments

    def input_prefix(self, view: PromptView) -> Fragments:
        return self._rail(self._tone(view))

    def text_footer(self, view: PromptView, width: int) -> Fragments:
        del width
        return self._footer(view)

    def menu(self, view: PromptView, state: MenuState, width: int) -> Fragments:
        symbols = self.style.symbols
        tone = self._tone(view)
        fragments = [*self.header(view, width), ("", "\n")]
        if view.kind == "confirm":
            row = self._confirm_row(view.choices, state.pointer, tone)
            return [*fragments, *row, ("", "\n"), *self._footer(view)]

        current = state.current()

        def option(index: int) -> Fragments:
            value, label = view.choices[index]
            focused = index == current
            if view.kind == "multiselect":
                on = index in state.selected
                mark = symbols.checked if on else symbols.unchecked
            else:
                on = focused
                mark = symbols.selected if on else symbols.unselected

            return [
                *self._rail(tone),
                ("success" if on else "muted", mark),
                ("", " "),
                ("focus" if focused else "option", label or value),
            ]

        rows = list_fragments(self.style.lists, state, self._rail(tone), option)

        return [*fragments, *rows, ("", "\n"), *self._footer(view)]

    def confirm_width(self, choices: Sequence[Choice]) -> int:
        return fragments_width(self._confirm_row(choices, 0, "accent"))

    def answered(self, question: Question, display: str) -> Fragments:
        symbols = self.style.symbols
        return [
            ("muted", f"{symbols.line}\n"),
            ("success", symbols.done),
            ("", self.gap),
            ("muted", question.prompt),
            ("", "\n"),
            ("muted", symbols.line),
            ("", self.gap),
            ("answer", display),
        ]

    def error_line(self, message: str) -> Fragments:
        return [*self._rail("error"), ("error", message)]

    def _confirm_row(self, choices: Sequence[Choice], pointer: int, tone: str) -> Fragments:
        symbols = self.style.symbols
        buttons: list[Fragments] = []
        for index, (value, label) in enumerate(choices):
            on = index == pointer
            buttons.append(
                [
                    ("success" if on else "muted", symbols.selected if on else symbols.unselected),
                    ("", " "),
                    ("focus" if on else "option", label or value),
                ]
            )

        separator = ("muted", f"  {symbols.separator}  ")

        return [*self._rail(tone), *join_lines(buttons, separator)]

    def _tone(self, view: PromptView) -> str:
        return "error" if view.error else "accent"

    def _rail(self, tone: str) -> Fragments:
        return [(tone, self.style.symbols.line), ("", self.gap)]

    def _footer(self, view: PromptView) -> Fragments:
        tone = self._tone(view)
        fragments: Fragments = [(tone, self.style.symbols.end), ("", self.gap)]
        if view.error:
            return [*fragments, ("error", view.error)]

        return fragments + hint_fragments(self.style.hints, view)


def build_layout(style: Style, questions: Sequence[Question]) -> Layout:
    match style:
        case CompactStyle():
            label_width = max((cell_len(question.prompt) for question in questions), default=0)
            return CompactLayout(style, label_width)
        case RailStyle():
            return RailLayout(style)


__all__ = [
    "CURSOR_ROLE",
    "CompactLayout",
    "Fragments",
    "Layout",
    "MenuState",
    "PromptKind",
    "PromptView",
    "RailLayout",
    "Step",
    "build_layout",
    "fragments_width",
    "hint_fragments",
    "join_lines",
    "list_fragments",
]
