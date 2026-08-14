from __future__ import annotations

import importlib.util
import inspect
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from jinja2 import Environment
from jinja2.ext import Extension

from sprout.errors import SproutManifestError
from sprout.manifest import (
    ApplyCallable,
    CliBooleanStyle,
    CreatedPaths,
    Manifest,
    ManifestContext,
    QuestionsSource,
    SkipPredicate,
    TitleCallable,
)
from sprout.prompt.question import AnswerMap, Question
from sprout.prompt.style import Style


@dataclass(frozen=True)
class ManifestReader:
    values: Mapping[str, object]

    def optional(self, name: str) -> Any | None:  # noqa: ANN401 - sprout.py entries are user-defined.
        return self.values.get(name)

    def questions(self) -> QuestionsSource:
        questions_obj = self.optional("questions")
        if questions_obj is None:
            raise SproutManifestError("sprout.py must define a questions variable.")

        if isinstance(questions_obj, Sequence) and not isinstance(
            questions_obj, (str, bytes, bytearray)
        ):
            return validate_questions_sequence(questions_obj)

        if callable(questions_obj):
            validate_questions_signature(questions_obj)

            def resolve(env: Environment, destination: Path) -> Sequence[Question]:
                return validate_questions_sequence(questions_obj(env, destination))

            return resolve

        raise SproutManifestError("questions in sprout.py must be a sequence or a callable.")

    def apply(self) -> ApplyCallable | None:
        apply_obj = self.optional("apply")
        if apply_obj is None:
            return None
        if not callable(apply_obj):
            raise SproutManifestError("apply in sprout.py must be a callable if provided.")

        validate_context_hook_signature(apply_obj, "apply")

        def apply(context: ManifestContext) -> CreatedPaths:
            return normalize_apply_result(apply_obj(context))

        return apply

    def style(self) -> Style | None:
        style_obj = self.optional("style")
        if style_obj is None:
            return None
        if not isinstance(style_obj, Style):
            raise SproutManifestError("style in sprout.py must be an instance of sprout.Style.")

        return style_obj

    def extensions(self) -> tuple[type[Extension], ...] | None:
        extensions_obj = self.optional("extensions")
        if extensions_obj is None:
            return None

        if not isinstance(extensions_obj, Sequence) or isinstance(
            extensions_obj,
            (str, bytes, bytearray),
        ):
            raise SproutManifestError(
                "extensions in sprout.py must be a sequence of Jinja2 extensions."
            )

        checked: list[type[Extension]] = []
        for extension in extensions_obj:
            if not isinstance(extension, type) or not issubclass(extension, Extension):
                raise SproutManifestError(
                    "each entry in extensions must be a Jinja2 Extension subclass."
                )

            checked.append(extension)

        return tuple(checked)

    def title(self) -> str | TitleCallable | None:
        title_obj = self.optional("title")
        if title_obj is None:
            return None

        if isinstance(title_obj, str):
            return title_obj

        if callable(title_obj):
            validate_context_hook_signature(title_obj, "title")

            def title(context: ManifestContext) -> str | None:
                result = title_obj(context)
                if result is None or isinstance(result, str):
                    return result

                raise SproutManifestError("title() must return a string or None.")

            return title

        raise SproutManifestError("title in sprout.py must be a string or a callable.")

    def template_dir(self) -> str | Path | None:
        template_dir_obj = self.optional("template_dir")
        if template_dir_obj is None:
            return None
        if not isinstance(template_dir_obj, (str, Path)):
            raise SproutManifestError("template_dir in sprout.py must be a string or a Path.")

        return template_dir_obj

    def cli_boolean_style(self) -> CliBooleanStyle:
        style_obj = self.optional("cli_boolean_style")
        if style_obj is None:
            return "flags"
        if style_obj == "flags":
            return "flags"
        if style_obj == "yes-no":
            return "yes-no"

        raise SproutManifestError("cli_boolean_style in sprout.py must be 'flags' or 'yes-no'.")

    def skip(self) -> SkipPredicate | None:
        skip_obj = self.optional("should_skip_file")
        if skip_obj is None:
            return None

        if not callable(skip_obj):
            raise SproutManifestError(
                "should_skip_file in sprout.py must be a callable taking (relative_path: str, answers)."
            )

        validate_skip_signature(skip_obj)

        def should_skip(relative_path: str, answers: AnswerMap) -> bool:
            result = skip_obj(relative_path, answers)
            if not isinstance(result, bool):
                raise SproutManifestError("should_skip_file in sprout.py must return a bool.")

            return result

        return should_skip


def normalize_apply_result(result: Any) -> CreatedPaths:  # noqa: ANN401 - apply hooks are user-defined.
    if result is None:
        return None
    if isinstance(result, (str, Path)):
        return [result]

    if isinstance(result, Sequence):
        paths: list[Path | str] = []
        for item in result:
            if not isinstance(item, (str, Path)):
                raise SproutManifestError(
                    "apply() must return None, a path, or a sequence of paths."
                )

            paths.append(item)

        return paths

    raise SproutManifestError("apply() must return None, a path, or a sequence of paths.")


def invoke_context_hook(
    hook: ApplyCallable | TitleCallable,
    context: ManifestContext,
    *,
    hook_name: str,
) -> CreatedPaths | Path | str | None:
    validate_context_hook_signature(hook, hook_name)

    return hook(context)


def validate_context_hook_signature(hook: Callable[..., object], hook_name: str) -> None:
    try:
        signature = inspect.signature(hook)
    except (TypeError, ValueError) as e:
        raise SproutManifestError(f"failed to inspect {hook_name}(): {e}") from e

    parameters = tuple(signature.parameters.values())
    allowed_kinds = {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }
    valid_shape = (
        len(parameters) == 1
        and parameters[0].name == "context"
        and parameters[0].kind in allowed_kinds
        and parameters[0].default is inspect.Parameter.empty
    )

    if not valid_shape:
        raise SproutManifestError(
            f"{hook_name}() in sprout.py must accept exactly one parameter: context."
        )


def load_manifest_module(template_dir: Path, manifest_path: Path) -> ModuleType:
    module_name = "sprout_template_manifest"
    spec = importlib.util.spec_from_file_location(module_name, manifest_path)
    if spec is None or spec.loader is None:
        raise SproutManifestError(f"unable to load manifest from {manifest_path}.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    template_path = str(template_dir)
    added_to_path = False
    try:
        if template_path not in sys.path:
            sys.path.insert(0, template_path)
            added_to_path = True

        spec.loader.exec_module(module)
    finally:
        if added_to_path:
            try:
                sys.path.remove(template_path)
            except ValueError:
                pass

        sys.modules.pop(module_name, None)

    return module


def validate_questions_signature(questions: Callable[..., object]) -> None:
    try:
        signature = inspect.signature(questions)
    except (TypeError, ValueError) as e:
        raise SproutManifestError(
            "questions callable in sprout.py must accept (env, destination) parameters."
        ) from e

    parameters = tuple(signature.parameters.values())
    allowed_kinds = {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }
    valid_shape = len(parameters) == 2 and all(
        parameter.kind in allowed_kinds for parameter in parameters
    )

    if not valid_shape:
        raise SproutManifestError(
            "questions callable in sprout.py must accept exactly two positional "
            "parameters: (env, destination)."
        )


def validate_questions_sequence(value: Any) -> Sequence[Question]:  # noqa: ANN401 - manifests are user-defined.
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise SproutManifestError("questions must be a sequence of Question instances.")

    questions: list[Question] = []
    for item in value:
        if not isinstance(item, Question):
            raise SproutManifestError("each entry in questions must be a Question instance.")

        questions.append(item)

    return questions


def validate_skip_signature(skip: Callable[..., object]) -> None:
    try:
        signature = inspect.signature(skip)
    except (TypeError, ValueError) as e:
        raise SproutManifestError(
            "should_skip_file in sprout.py must be a callable with "
            "(relative_path: str, answers) parameters."
        ) from e

    parameters = tuple(signature.parameters.values())
    allowed_kinds = {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }
    valid_shape = len(parameters) == 2 and all(
        parameter.kind in allowed_kinds for parameter in parameters
    )

    if not valid_shape:
        raise SproutManifestError(
            "should_skip_file in sprout.py must accept exactly two positional "
            "parameters: (relative_path: str, answers)."
        )


def load_manifest(template_dir: Path) -> Manifest:
    manifest_path = template_dir / "sprout.py"
    if not manifest_path.is_file():
        raise SproutManifestError(f"template source {template_dir} is missing sprout.py.")

    module = load_manifest_module(template_dir, manifest_path)
    reader = ManifestReader(vars(module))

    return Manifest(
        questions=reader.questions(),
        apply=reader.apply(),
        template_dir=reader.template_dir(),
        skip=reader.skip(),
        style=reader.style(),
        extensions=reader.extensions(),
        title=reader.title(),
        cli_boolean_style=reader.cli_boolean_style(),
    )


def resolve_questions(
    source: QuestionsSource,
    env: Environment,
    destination: Path,
) -> Sequence[Question]:
    resolved = source(env, destination) if callable(source) else source

    return validate_questions_sequence(resolved)


__all__ = [
    "ManifestReader",
    "invoke_context_hook",
    "load_manifest",
    "load_manifest_module",
    "normalize_apply_result",
    "resolve_questions",
    "validate_context_hook_signature",
    "validate_questions_sequence",
]
