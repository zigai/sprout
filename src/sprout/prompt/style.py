from __future__ import annotations

from dataclasses import dataclass, field

type KeyHint = tuple[str, str]


@dataclass
class Palette:
    """
    Colors for prompt rendering, written as Rich style strings such as `"bold green"`,
    `"black on bright_cyan"`, or `"#22d3ee"`. Named colors and empty strings follow the
    terminal theme.
    """

    brand: str = "bold #4ade80"
    accent: str = "#7dd3fc"
    success: str = "#4ade80"
    error: str = "#f87171"
    title: str = "bold"
    answer: str = ""
    option: str = ""
    focus: str = "bold underline"
    highlight: str = "bold #e0f2fe on #075985"
    muted: str = "#71717a"
    key: str = "#d4d4d8 on #3f3f46"


@dataclass
class Hints:
    """Key hints shown under live prompts as `(key, action)` pairs."""

    show: bool = True
    text: tuple[KeyHint, ...] = (("enter", "submit"),)
    text_default: tuple[KeyHint, ...] = (("tab", "use default"),)
    confirm: tuple[KeyHint, ...] = (("←→", "choose"), ("enter", "confirm"))
    select: tuple[KeyHint, ...] = (("↑↓", "move"), ("enter", "select"))
    multiselect: tuple[KeyHint, ...] = (
        ("↑↓", "move"),
        ("space", "toggle"),
        ("ctrl+a", "all"),
        ("enter", "confirm"),
    )


@dataclass
class ListOptions:
    """
    Scrolling and search for select and multiselect lists.

    Attributes:
        max_visible (int): Most options shown at once. Short terminals show fewer.
            Defaults to 8.
        search (bool): Whether typing filters the options. Defaults to True.
        search_prefix (str): Text shown before the search query. Defaults to "/".
        search_placeholder (str): Shown in the search line of a scrolling list before anything
            is typed. Defaults to "Type to search".
        more_above (str): Shown above the visible options; `{count}` is the hidden count.
        more_below (str): Shown below the visible options; `{count}` is the hidden count.
        no_matches (str): Shown when the search matches no option.
    """

    max_visible: int = 8
    search: bool = True
    search_prefix: str = "/"
    search_placeholder: str = "Type to search"
    more_above: str = "↑ {count} more"
    more_below: str = "↓ {count} more"
    no_matches: str = "No matches"


@dataclass
class CompactSymbols:
    active: str = "●"
    done: str = "✓"
    error: str = "✕"
    checked: str = "■"
    unchecked: str = "□"
    rule: str = "─"


@dataclass
class RailSymbols:
    start: str = "┌"
    line: str = "│"
    end: str = "└"
    active: str = "◆"
    done: str = "◇"
    error: str = "▲"
    selected: str = "●"
    unselected: str = "○"
    checked: str = "■"
    unchecked: str = "□"
    separator: str = "/"


@dataclass
class CompactStyle:
    """
    Render each answered question as one aligned `label  value` line.

    Attributes:
        palette (Palette): Colors for every prompt element.
        symbols (CompactSymbols): Markers for active, answered, and failed questions.
        hints (Hints): Key hints shown under live prompts.
        lists (ListOptions): Scrolling and search for long option lists.
        brand (str): Name shown before the title in the header line. Empty hides it.
            Defaults to "sprout".
        show_progress (bool): Whether to show the `step/total` counter next to the question.
            Defaults to True.
        max_width (int): Maximum width of the prompt area in cells. Defaults to 64.
        max_label_width (int): Longest label width used to align answers. Longer labels are
            shortened with "…" in the answer list. Defaults to 32.
    """

    palette: Palette = field(default_factory=Palette)
    symbols: CompactSymbols = field(default_factory=CompactSymbols)
    hints: Hints = field(default_factory=Hints)
    lists: ListOptions = field(default_factory=ListOptions)
    brand: str = "sprout"
    show_progress: bool = True
    max_width: int = 64
    max_label_width: int = 32


@dataclass
class RailStyle:
    """
    Render questions along a vertical line, with each answer under its question.

    Attributes:
        palette (Palette): Colors for every prompt element. The brand defaults to a badge.
        symbols (RailSymbols): Line pieces and markers.
        hints (Hints): Key hints shown under live prompts.
        lists (ListOptions): Scrolling and search for long option lists.
        brand (str): Name shown before the title on the opening line. Empty hides it.
            Defaults to "sprout".
    """

    palette: Palette = field(default_factory=lambda: Palette(brand="bold #052e16 on #4ade80"))
    symbols: RailSymbols = field(default_factory=RailSymbols)
    hints: Hints = field(default_factory=Hints)
    lists: ListOptions = field(default_factory=ListOptions)
    brand: str = "sprout"


type Style = CompactStyle | RailStyle


__all__ = [
    "CompactStyle",
    "CompactSymbols",
    "Hints",
    "KeyHint",
    "ListOptions",
    "Palette",
    "RailStyle",
    "RailSymbols",
    "Style",
]
