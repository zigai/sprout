from __future__ import annotations

from sprout.prompt.layout import CURSOR_ROLE, MenuState, list_fragments
from sprout.prompt.style import ListOptions

CHOICES = [
    ("mit", "MIT License"),
    ("apache", "Apache License 2.0"),
    ("gpl3", "GNU General Public License v3.0"),
    ("gpl2", "GNU General Public License v2.0"),
    ("lgpl", "GNU Lesser General Public License"),
    ("bsd", "BSD 3-Clause"),
]


def _text(state: MenuState, lists: ListOptions | None = None) -> list[str]:
    fragments = list_fragments(
        lists or ListOptions(),
        state,
        [("", "  ")],
        lambda index: [("", f"  {CHOICES[index][1]}")],
    )
    return [line.rstrip() for line in "".join(text for _role, text in fragments).splitlines()]


def test_search_requires_every_word_in_label_or_value_ignoring_case() -> None:
    state = MenuState(choices=CHOICES)

    state.search("gnu V3")
    assert state.matches() == [2]

    state.search("GPL2")
    assert state.matches() == [3]


def test_typing_moves_pointer_to_top_match_and_clearing_keeps_it() -> None:
    state = MenuState(choices=CHOICES, pointer=3)

    state.search("general")
    assert state.pointer == 2

    state.move(2)
    state.search("")
    assert state.pointer == 4


def test_search_without_matches_leaves_no_current_option() -> None:
    state = MenuState(choices=CHOICES, pointer=1)

    state.search("zzz")

    assert state.current() is None
    assert state.window() == ([], 0, 0)


def test_selection_survives_search_that_hides_it() -> None:
    state = MenuState(choices=CHOICES, selected={0})

    state.search("gnu")
    state.search("")

    assert state.selected == {0}


def test_move_wraps_within_matches_and_page_moves_clamp() -> None:
    state = MenuState(choices=CHOICES)
    state.search("gnu")

    state.move(-1)
    assert state.pointer == 4

    state.move(10, wrap=False)
    assert state.pointer == 4
    state.move(-10, wrap=False)
    assert state.pointer == 2


def test_window_follows_pointer_and_counts_hidden_options() -> None:
    state = MenuState(choices=CHOICES, visible=3)

    assert state.window() == ([0, 1, 2], 0, 3)

    state.jump(last=True)
    assert state.window() == ([3, 4, 5], 3, 0)

    state.move(-3, wrap=False)
    assert state.window() == ([2, 3, 4], 2, 1)


def test_scrolling_list_shows_search_line_and_more_markers() -> None:
    state = MenuState(choices=CHOICES, pointer=3)
    state.resize(3)

    lines = _text(state)

    assert lines[0] == "  / Type to search"
    assert lines[1] == "  ↑ 1 more"
    assert lines[2:5] == [
        "  Apache License 2.0",
        "  GNU General Public License v3.0",
        "  GNU General Public License v2.0",
    ]
    assert lines[5] == "  ↓ 2 more"


def test_marker_lines_stay_reserved_when_nothing_is_hidden_on_that_side() -> None:
    state = MenuState(choices=CHOICES, visible=3)
    state.search("gnu")

    lines = _text(state)

    assert lines[0] == "  / gnu"
    assert [line.strip() for line in (lines[1], lines[-1])] == ["", ""]
    assert len(lines) == 6


def test_short_list_hides_search_line_until_typing_and_uses_custom_text() -> None:
    lists = ListOptions(search_prefix="?", no_matches="nothing")
    state = MenuState(choices=CHOICES[:2])

    assert _text(state, lists) == ["  MIT License", "  Apache License 2.0"]

    state.search("zzz")
    assert _text(state, lists) == ["  ? zzz", "  nothing"]


def test_disabled_search_never_shows_search_line() -> None:
    state = MenuState(choices=CHOICES, visible=3)

    assert not any("Type to search" in line for line in _text(state, ListOptions(search=False)))


def test_search_line_places_cursor_after_query_or_before_placeholder() -> None:
    state = MenuState(choices=CHOICES, visible=3)
    lines = list_fragments(ListOptions(), state, [], lambda index: [("", CHOICES[index][1])])
    search_line = lines[: lines.index(("", "\n"))]
    assert [text for role, text in search_line if role != CURSOR_ROLE] == ["/ ", "Type to search"]
    assert search_line.index((CURSOR_ROLE, "")) == 1

    state.search("gnu")
    lines = list_fragments(ListOptions(), state, [], lambda index: [("", CHOICES[index][1])])
    assert lines[:3] == [("muted", "/ "), ("answer", "gnu"), (CURSOR_ROLE, "")]
