from __future__ import annotations

from sprout.cli import Manifest, execute_manifest
from sprout.extensions import CurrentYearExtension, GitDefaultsExtension, build_environment
from sprout.prompt import (
    ask_question,
    collect_answers,
    confirm_overwrite,
    console,
    supports_live_interaction,
)
from sprout.question import Question
from sprout.style import ErrorStyle, InlineStyle, MenuStyle, PromptStyle, Style, SummaryStyle
from sprout.validators import ValidatorFn, ValidatorType, validate_repository_url

__all__ = [
    "Manifest",
    "execute_manifest",
    "GitDefaultsExtension",
    "CurrentYearExtension",
    "build_environment",
    "Question",
    "ErrorStyle",
    "InlineStyle",
    "MenuStyle",
    "PromptStyle",
    "Style",
    "SummaryStyle",
    "ValidatorFn",
    "ValidatorType",
    "validate_repository_url",
    "ask_question",
    "collect_answers",
    "confirm_overwrite",
    "console",
    "supports_live_interaction",
]
