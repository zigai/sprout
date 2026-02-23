from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PromptStyle:
    """
    Configure prompt header rendering.

    Attributes:
        prefix (str): Prefix shown before each question prompt.
        prefix_style (str): Rich style string applied to `prefix`.
        text_style (str): Rich style string applied to question text.
        help_style (str): Rich style string applied to helper text.
    """

    prefix: str = "? "
    prefix_style: str = "bold cyan"
    text_style: str = "bold white"
    help_style: str = "dim"


@dataclass
class InlineStyle:
    """
    Configure inline two-choice rendering.

    Attributes:
        selected_icon (str): Icon shown for the currently selected choice.
        unselected_icon (str): Icon shown for unselected choices.
        separator (str): Separator inserted between inline choices.
        prompt_style (str): Rich style string applied to the prompt row.
        bullet_selected_style (str): Rich style string for selected choice icons.
        bullet_unselected_style (str): Rich style string for unselected choice icons.
        text_selected_style (str): Rich style string for selected choice labels.
        text_unselected_style (str): Rich style string for unselected choice labels.
        instruction (str): Instruction text shown near the inline selector.
        instruction_style (str): Rich style string applied to `instruction`.
    """

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
    """
    Configure vertical menu rendering for multi-choice prompts.

    Attributes:
        caret_icon (str): Caret marker shown before the active menu row.
        caret_style (str): Rich style string applied to `caret_icon`.
        bullet_selected_icon (str): Icon shown for selected choices.
        bullet_unselected_icon (str): Icon shown for unselected choices.
        bullet_selected_style (str): Rich style string for selected choice icons.
        bullet_unselected_style (str): Rich style string for unselected choice icons.
        text_selected_style (str): Rich style string for selected choice labels.
        text_unselected_style (str): Rich style string for unselected choice labels.
        instruction_single (str): Instruction text for single-select menus.
        instruction_multi (str): Instruction text for multi-select menus.
        instruction_style (str): Rich style string applied to instruction text.
    """

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
    """
    Configure answer summary rendering.

    Attributes:
        prefix (str): Prefix displayed before each summarized answer.
        selected_style (str): Rich style string applied to selected answer text.
        dim_style (str): Rich style string applied to de-emphasized summary text.
    """

    prefix: str = "  → "
    selected_style: str = "bold green"
    dim_style: str = "dim"


@dataclass
class ErrorStyle:
    """
    Configure validation error rendering.

    Attributes:
        label (str): Label displayed before each error message.
        style (str): Rich style string applied to the error label.
    """

    label: str = "Error:"
    style: str = "bold red"


@dataclass
class Style:
    """
    Aggregate all prompt rendering styles.

    Attributes:
        prompt (PromptStyle): Style configuration for prompt headers.
        inline (InlineStyle): Style configuration for inline yes/no-like selectors.
        menu (MenuStyle): Style configuration for vertical choice menus.
        summary (SummaryStyle): Style configuration for printed answer summaries.
        error (ErrorStyle): Style configuration for validation errors.
        default_style (str): Rich style string used as a default fallback.
        input_prefix (str): Prefix shown before text input prompts.
    """

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
