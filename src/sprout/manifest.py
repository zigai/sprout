from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jinja2 import Environment
from jinja2.ext import Extension

from sprout.prompt.question import AnswerMap, DefaultValue, Question
from sprout.prompt.style import Style


@dataclass(frozen=True)
class ManifestContext:
    env: Environment
    template_dir: Path
    template_root: Path
    destination: Path
    answers: dict[str, DefaultValue]
    style: Style


type CreatedPaths = Sequence[Path | str] | None
type ApplyCallable = Callable[[ManifestContext], CreatedPaths | Path | str]
type TitleCallable = Callable[[ManifestContext], str | None]
SkipPredicate = Callable[[str, AnswerMap], bool]
QuestionsCallable = Callable[[Environment, Path], Sequence[Question]]
QuestionsSource = Sequence[Question] | QuestionsCallable
CliBooleanStyle = Literal["flags", "yes-no"]


@dataclass(frozen=True)
class Manifest:
    """
    Describe a loaded `sprout.py` manifest.

    Attributes:
        questions (QuestionsSource): Question sequence or callable that builds questions.
        apply (ApplyCallable | None): Optional custom file-generation hook.
        template_dir (str | Path | None): Optional template subdirectory relative to template root.
        skip (SkipPredicate | None): Optional predicate that skips files during rendering.
        style (Style | None): Optional style overrides for prompt rendering.
        extensions (Sequence[type[Extension]] | None): Optional Jinja extension classes.
        title (str | TitleCallable | None): Optional static or dynamic title renderer.
        cli_boolean_style (CliBooleanStyle): How yes/no questions are exposed as CLI options.
    """

    questions: QuestionsSource
    apply: ApplyCallable | None = None
    template_dir: str | Path | None = None
    skip: SkipPredicate | None = None
    style: Style | None = None
    extensions: Sequence[type[Extension]] | None = None
    title: str | TitleCallable | None = None
    cli_boolean_style: CliBooleanStyle = "flags"


__all__ = [
    "ApplyCallable",
    "CliBooleanStyle",
    "CreatedPaths",
    "Manifest",
    "ManifestContext",
    "QuestionsCallable",
    "QuestionsSource",
    "SkipPredicate",
    "TitleCallable",
]
