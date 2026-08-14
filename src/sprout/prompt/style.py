from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PromptStyle:
    """Configure prompt header rendering."""

    prefix: str = "? "
    prefix_style: str = "bold cyan"
    text_style: str = "bold white"
    help_style: str = "dim"


@dataclass
class InlineStyle:
    """Configure inline two-choice rendering."""

    selected_icon: str = "●"
    unselected_icon: str = "○"
    separator: str = " / "
    prompt_style: str = "bold white"
    bullet_selected_style: str = "bold"
    bullet_unselected_style: str = "dim"
    text_selected_style: str = "bold"
    text_unselected_style: str = ""
    instruction: str = "←/→ move  Enter select"
    instruction_style: str = "dim"


@dataclass
class MenuStyle:
    """Configure vertical menu rendering for multi-choice prompts."""

    caret_icon: str = "▌  "
    caret_style: str = "bold ansicyan"
    bullet_selected_icon: str = "● "
    bullet_unselected_icon: str = "○ "
    bullet_selected_style: str = "bold"
    bullet_unselected_style: str = "dim"
    text_selected_style: str = "bold"
    text_unselected_style: str = ""
    instruction_single: str = "↑/↓ move  Enter select"
    instruction_multi: str = "↑/↓ move  Space toggle  Enter confirm"
    instruction_style: str = "dim"


@dataclass
class SummaryStyle:
    """Configure answer summary rendering."""

    prefix: str = "  → "
    selected_style: str = "bold green"
    dim_style: str = "dim"


@dataclass
class ErrorStyle:
    """Configure validation error rendering."""

    label: str = "Error:"
    style: str = "bold red"


@dataclass
class Style:
    """Aggregate all prompt rendering styles."""

    prompt: PromptStyle = field(default_factory=PromptStyle)
    inline: InlineStyle = field(default_factory=InlineStyle)
    menu: MenuStyle = field(default_factory=MenuStyle)
    summary: SummaryStyle = field(default_factory=SummaryStyle)
    error: ErrorStyle = field(default_factory=ErrorStyle)
    default_style: str = "dim"
    input_prefix: str = "›"  # noqa: RUF001


__all__ = [
    "ErrorStyle",
    "InlineStyle",
    "MenuStyle",
    "PromptStyle",
    "Style",
    "SummaryStyle",
]
