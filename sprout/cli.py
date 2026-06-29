from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import inspect
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from interfacy.argparse_backend.argument_parser import ArgumentParser, namespace_to_dict
from jinja2 import Environment
from jinja2.ext import Extension
from rich.text import Text

from sprout.extensions import build_environment
from sprout.prompt import ask_question, collect_answers, console, supports_live_interaction
from sprout.question import AnswerMap, DefaultValue, Question
from sprout.style import Style


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


@dataclass(frozen=True)
class TemplateCLIArgs:
    """
    Hold normalized CLI arguments for template execution.

    Attributes:
        template_src (str): Template source path, Git URL, or owner/repo shorthand.
        destination (Path): Absolute destination directory path.
        force (bool): Whether to allow overwriting in a non-empty destination.
    """

    template_src: str
    destination: Path
    force: bool = False


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
    """

    questions: QuestionsSource
    apply: ApplyCallable | None = None
    template_dir: str | Path | None = None
    skip: SkipPredicate | None = None
    style: Style | None = None
    extensions: Sequence[type[Extension]] | None = None
    title: str | TitleCallable | None = None


@dataclass(frozen=True)
class PreparedTemplate:
    """
    Hold preloaded manifest state used for CLI argument parsing and generation.

    Attributes:
        template_src (str): Template source used for this prepared manifest.
        template_dir (Path): Resolved local template directory.
        manifest (Manifest): Loaded manifest definition.
        cleanup (Callable[[], None]): Cleanup callback for temporary resources.
        questions (Sequence[Question]): Resolved questions available for CLI flags.
    """

    template_src: str
    template_dir: Path
    manifest: Manifest
    cleanup: Callable[[], None]
    questions: Sequence[Question]


@dataclass(frozen=True)
class CLIInvocation:
    template_src: str | None
    destination: Path | None
    help_requested: bool

    @classmethod
    def from_args(cls, args: Sequence[str] | None) -> CLIInvocation:
        template_src, destination = _extract_template_destination(args)

        return cls(
            template_src=template_src,
            destination=destination,
            help_requested=_has_help_option(args),
        )


@dataclass(frozen=True)
class ManifestReader:
    values: Mapping[str, object]

    def optional(self, name: str) -> object | None:
        return self.values.get(name)

    def questions(self) -> QuestionsSource:
        questions_obj = self.optional("questions")
        if questions_obj is None:
            raise SystemExit("sprout.py must define a questions variable.")

        if isinstance(questions_obj, Sequence) and not isinstance(
            questions_obj, (str, bytes, bytearray)
        ):
            return list(questions_obj)

        if callable(questions_obj):
            _validate_questions_signature(questions_obj)

            def resolve(env: Environment, destination: Path) -> Sequence[Question]:
                return _validate_questions_sequence(questions_obj(env, destination))

            return resolve

        raise SystemExit("questions in sprout.py must be a sequence or a callable.")

    def apply(self) -> ApplyCallable | None:
        apply_obj = self.optional("apply")
        if apply_obj is None:
            return None
        if not callable(apply_obj):
            raise SystemExit("apply in sprout.py must be a callable if provided.")

        _validate_context_hook_signature(apply_obj, "apply")

        def apply(context: ManifestContext) -> CreatedPaths:
            return _normalise_apply_result(apply_obj(context))

        return apply

    def style(self) -> Style | None:
        style_obj = self.optional("style")
        if style_obj is None:
            return None
        if not isinstance(style_obj, Style):
            raise SystemExit("style in sprout.py must be an instance of sprout.style.Style.")

        return style_obj

    def extensions(self) -> tuple[type[Extension], ...] | None:
        extensions_obj = self.optional("extensions")
        if extensions_obj is None:
            return None

        if not isinstance(extensions_obj, Sequence) or isinstance(
            extensions_obj,
            (str, bytes, bytearray),
        ):
            raise SystemExit("extensions in sprout.py must be a sequence of Jinja2 extensions.")

        checked: list[type[Extension]] = []
        for extension in extensions_obj:
            if not isinstance(extension, type) or not issubclass(extension, Extension):
                raise SystemExit("each entry in extensions must be a Jinja2 Extension subclass.")

            checked.append(extension)

        return tuple(checked)

    def title(self) -> str | TitleCallable | None:
        title_obj = self.optional("title")
        if title_obj is None:
            return None

        if isinstance(title_obj, str):
            return title_obj

        if callable(title_obj):
            _validate_context_hook_signature(title_obj, "title")

            def title(context: ManifestContext) -> str | None:
                result = title_obj(context)
                if result is None or isinstance(result, str):
                    return result

                raise SystemExit("title() must return a string or None.")

            return title

        raise SystemExit("title in sprout.py must be a string or a callable.")

    def template_dir(self) -> str | Path | None:
        template_dir_obj = self.optional("template_dir")
        if template_dir_obj is None:
            return None
        if not isinstance(template_dir_obj, (str, Path)):
            raise SystemExit("template_dir in sprout.py must be a string or a Path.")

        return template_dir_obj

    def skip(self) -> SkipPredicate | None:
        skip_obj = self.optional("should_skip_file")
        if skip_obj is None:
            return None

        if not callable(skip_obj):
            raise SystemExit(
                "should_skip_file in sprout.py must be a callable taking (relative_path: str, answers)."
            )

        _validate_skip_signature(skip_obj)

        def should_skip(relative_path: str, answers: AnswerMap) -> bool:
            result = skip_obj(relative_path, answers)
            if not isinstance(result, bool):
                raise SystemExit("should_skip_file in sprout.py must return a bool.")

            return result

        return should_skip


def ensure_destination(path: Path, *, force: bool, style: Style | None = None) -> None:
    """
    Ensure destination directory exists and confirm overwrites when needed.

    Args:
        path (Path): Destination directory path.
        force (bool): Whether to skip overwrite confirmation for non-empty directories.
        style (Style | None): Optional style overrides used for confirmation prompts.

    Raises:
        SystemExit: If `path` points to a file or the user declines overwrite confirmation.
    """
    style = style or Style()

    if path.exists():
        if path.is_file():
            raise SystemExit(f"destination '{path}' is a file. Provide a directory path.")

        if any(path.iterdir()) and not force:
            console.print(Text(f"Destination '{path}' is not empty.", style="bold yellow"))

            if not _confirm_overwrite(path, style=style):
                raise SystemExit("aborted by user.")
    else:
        path.mkdir(parents=True, exist_ok=True)


def _confirm_overwrite(path: Path, *, style: Style) -> bool:
    if not supports_live_interaction():
        return False

    question = Question(
        key="overwrite",
        prompt=f"Allow overwriting files in '{path}'?",
        choices=[("yes", "Yes"), ("no", "No")],
        default="no",
    )
    answer = ask_question(question, {}, style)
    return answer == "yes"


def _merge_ignore_patterns(ignore: Sequence[str] | None) -> list[str]:
    patterns = list(ignore or ())
    for pattern in ("*.pyc", "*.pyo", "*.pyd", "*.swp", "*~", ".DS_Store"):
        if pattern not in patterns:
            patterns.append(pattern)

    return patterns


def _should_ignore_path(path: Path, ignore_patterns: Sequence[str]) -> bool:
    if "__pycache__" in path.parts:
        return True

    return any(fnmatch.fnmatch(path.name, pattern) for pattern in ignore_patterns)


class TemplateRenderer:
    """Render files from one template directory into one destination."""

    def __init__(
        self,
        *,
        env: Environment,
        template_dir: Path,
        destination: Path,
        answers: dict[str, DefaultValue],
        skip: SkipPredicate | None = None,
        render_paths: bool = False,
        ignore: Sequence[str] | None = None,
    ) -> None:
        self.env = env
        self.template_dir = template_dir
        self.destination = destination
        self.answers = answers
        self.skip = skip
        self.render_paths = render_paths
        self.ignore_patterns = _merge_ignore_patterns(ignore)

    def render(self) -> list[Path]:
        created: list[Path] = []

        for source in sorted(self.template_dir.rglob("*")):
            if source.is_dir() or _should_ignore_path(source, self.ignore_patterns):
                continue

            relative = source.relative_to(self.template_dir)
            relative_str = relative.as_posix()
            if self.skip and self.skip(relative_str, self.answers):
                continue

            target_relative = self._resolve_target_relative(source, relative)
            self._render_source_file(source, target_relative, relative_str)
            created.append(target_relative)

        return created

    def _resolve_target_relative(self, source: Path, relative: Path) -> Path:
        if self.render_paths:
            rendered = self.env.from_string(relative.as_posix()).render(**self.answers)
            target_relative = Path(rendered)
        else:
            target_relative = relative

        if source.suffix == ".jinja":
            target_relative = target_relative.with_suffix("")

        if target_relative == Path():
            raise SystemExit(f"rendered path for '{relative.as_posix()}' must not be empty.")

        if target_relative.is_absolute() or ".." in target_relative.parts:
            raise SystemExit(
                f"rendered path for '{relative.as_posix()}' must stay within the destination directory."
            )

        return target_relative

    def _render_source_file(self, source: Path, target_relative: Path, relative_str: str) -> None:
        target_path = self.destination / target_relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix == ".jinja":
            template = self.env.get_template(relative_str)
            target_path.write_text(template.render(**self.answers), encoding="utf-8")

            return

        shutil.copy2(source, target_path)


def render_templates(
    env: Environment | None,
    template_dir: Path,
    destination: Path,
    answers: dict[str, DefaultValue],
    *,
    skip: SkipPredicate | None = None,
    render_paths: bool = False,
    ignore: Sequence[str] | None = None,
    extensions: Sequence[type[Extension]] | None = None,
) -> list[Path]:
    """
    Render a template directory into ``destination``.

    - If ``render_paths`` is True, treat relative paths as Jinja templates and render them with
      ``answers`` (useful for names like ``"{{ package_name }}"``).
    - ``ignore`` is a list of glob patterns (matched against file name) and special names to skip.
    """
    if env is None:
        env = build_environment(template_dir, extensions=extensions or ())

    renderer = TemplateRenderer(
        env=env,
        template_dir=template_dir,
        destination=destination,
        answers=answers,
        skip=skip,
        render_paths=render_paths,
        ignore=ignore,
    )

    return renderer.render()


def summarize(created: Sequence[Path], destination: Path | None = None) -> None:
    """
    Print a summary of generated relative file paths.

    Args:
        created (Sequence[Path]): Created paths relative to the destination directory.
        destination (Path | None): Directory where files were generated.
    """
    if not created:
        return

    heading = "\nGenerated files"
    if destination is not None:
        heading = f"{heading} in {destination}"

    console.print(Text(heading, style="white"), soft_wrap=True)

    for path in created:
        console.print(Text(f"  • {path}", style="white"))


def _resolve_actual_template_dir(root: Path, declared: str | Path | None) -> Path:
    if declared is None or (isinstance(declared, str) and declared.strip() == ""):
        return (root / "template").resolve()

    path = Path(declared)

    return path if path.is_absolute() else (root / path).resolve()


def run_template(
    *,
    template_dir: Path,
    destination: Path,
    question_builder: Callable[[Environment, Path], Sequence[Question]],
    skip: SkipPredicate | None = None,
    extensions: Sequence[type[Extension]] | None = None,
    style: Style | None = None,
    initial_answers: dict[str, DefaultValue] | None = None,
    force: bool = False,
    banner: Callable[[], None] | None = None,
    summary: Callable[[Sequence[Path]], None] | None = None,
) -> tuple[dict[str, DefaultValue], Sequence[Path]]:
    """
    Generate files from a template directory and return answers with created paths.

    Args:
        template_dir (Path): Template directory that contains files to render.
        destination (Path): Output directory for generated files.
        question_builder (Callable[[Environment, Path], Sequence[Question]]): Callable that builds
            questions from the Jinja environment and destination path.
        skip (SkipPredicate | None): Optional predicate that skips files by relative path.
        extensions (Sequence[type[Extension]] | None): Optional Jinja extension classes.
        style (Style | None): Optional style overrides used while prompting.
        initial_answers (dict[str, DefaultValue] | None): Optional pre-filled answers keyed by question key.
        force (bool): Whether to skip overwrite confirmation for non-empty destinations.
        banner (Callable[[], None] | None): Optional callback invoked before prompting.
        summary (Callable[[Sequence[Path]], None] | None): Optional callback used to print a
            generation summary.

    Raises:
        SystemExit: If `template_dir` does not exist or destination checks fail.
    """
    if banner:
        banner()

    if not template_dir.exists():
        raise SystemExit(f"Template directory not found. Expected {template_dir} to exist.")

    answers, created = execute_manifest(
        Manifest(
            questions=question_builder,
            template_dir=".",
            skip=skip,
            style=style,
            extensions=extensions,
        ),
        template_dir=template_dir,
        destination=destination,
        force=force,
        initial_answers=initial_answers,
        summary=summary,
    )

    return answers, list(created or ())


class ManifestExecution:
    def __init__(
        self,
        manifest: Manifest,
        *,
        template_dir: Path,
        destination: Path,
        force: bool = False,
        initial_answers: dict[str, DefaultValue] | None = None,
        summary: Callable[[Sequence[Path]], None] | None = None,
    ) -> None:
        self.manifest = manifest
        self.template_root = template_dir
        self.destination = destination
        self.force = force
        self.initial_answers = initial_answers
        self.summary = summary
        self.style = manifest.style or Style()
        self.actual_template_dir = _resolve_actual_template_dir(
            self.template_root,
            manifest.template_dir,
        )
        self.env = build_environment(
            self.actual_template_dir,
            extensions=manifest.extensions or (),
        )
        self.answers: dict[str, DefaultValue] = {}

    def execute(self) -> tuple[dict[str, DefaultValue], Sequence[Path] | None]:
        _display_title(
            self.manifest.title,
            context=self._context(),
        )

        questions = _resolve_questions(self.manifest.questions, self.env, self.destination)
        self.answers = collect_answers(
            questions,
            style=self.style,
            initial_answers=self.initial_answers,
        )
        ensure_destination(self.destination, force=self.force, style=self.style)

        created = self._create_files()
        if created is None:
            return self.answers, None

        created_paths = _normalise_created(created, self.destination)
        self._summarize_created(created_paths)

        return self.answers, created_paths

    def _context(self) -> ManifestContext:
        return ManifestContext(
            env=self.env,
            template_dir=self.actual_template_dir,
            template_root=self.template_root,
            destination=self.destination,
            answers=self.answers,
            style=self.style,
        )

    def _create_files(self) -> CreatedPaths:
        if self.manifest.apply is not None:
            return _invoke_apply(
                self.manifest.apply,
                context=self._context(),
            )

        if not self.actual_template_dir.exists():
            raise SystemExit(
                f"Template directory not found. Expected {self.actual_template_dir} to exist."
            )

        return render_templates(
            self.env,
            self.actual_template_dir,
            self.destination,
            self.answers,
            skip=self.manifest.skip,
            render_paths=True,
        )

    def _summarize_created(self, created_paths: Sequence[Path]) -> None:
        if not created_paths:
            console.print(Text("No files were generated.", style="yellow"))
            return

        if self.summary:
            self.summary(created_paths)
            return

        summarize(created_paths, self.destination)


def execute_manifest(
    manifest: Manifest,
    *,
    template_dir: Path,
    destination: Path,
    force: bool = False,
    initial_answers: dict[str, DefaultValue] | None = None,
    summary: Callable[[Sequence[Path]], None] | None = None,
) -> tuple[dict[str, DefaultValue], Sequence[Path] | None]:
    """
    Execute a manifest workflow and return answers with created paths.

    Args:
        manifest (Manifest): Loaded manifest definition to execute.
        template_dir (Path): Template root that contains `sprout.py` and template files.
        destination (Path): Output directory for generated files.
        force (bool): Whether to skip overwrite confirmation for non-empty destinations.
        initial_answers (dict[str, DefaultValue] | None): Optional pre-filled answers keyed by question key.
        summary (Callable[[Sequence[Path]], None] | None): Optional callback used to print a
            generation summary.

    Raises:
        SystemExit: If manifest hooks fail validation or template directories are missing.
    """
    return ManifestExecution(
        manifest,
        template_dir=template_dir,
        destination=destination,
        force=force,
        initial_answers=initial_answers,
        summary=summary,
    ).execute()


def generate(
    template: str,
    destination: str | Path,
    *,
    force: bool = False,
) -> int:
    """
    Generate a project from a sprout manifest.

    The manifest can define questions and an optional apply hook.

    Args:
        template: path or git repository containing a sprout.py manifest
        destination: target directory for the generated project
        force: overwrite files in the destination directory if they already exist
    """
    return _run_generate(template, destination, force=force, initial_answers=None, prepared=None)


def _run_generate(
    template: str,
    destination: str | Path,
    *,
    force: bool,
    initial_answers: dict[str, DefaultValue] | None,
    prepared: PreparedTemplate | None,
) -> int:
    destination_path = Path(destination).expanduser().resolve()
    args = TemplateCLIArgs(
        template_src=template,
        destination=destination_path,
        force=force,
    )
    cleanup: Callable[[], None] | None = None
    try:
        if prepared is not None and prepared.template_src == template:
            template_dir = prepared.template_dir
            manifest = prepared.manifest
        else:
            template_dir, cleanup = _prepare_template_source(args.template_src)
            manifest = _load_manifest(template_dir)

        execute_manifest(
            manifest,
            template_dir=template_dir,
            destination=args.destination,
            force=args.force,
            initial_answers=initial_answers,
        )
    except KeyboardInterrupt:  # pragma: no cover - interactive
        console.print(Text("Aborted by user.", style="bold red"))
        return 1
    finally:
        if cleanup:
            cleanup()

    return 0


def _normalise_created(created: Sequence[Path | str], destination: Path) -> list[Path]:
    results: list[Path] = []
    for item in created:
        path = Path(item)
        if path.is_absolute():
            try:
                path = path.relative_to(destination)
            except ValueError:
                pass

        results.append(path)

    return results


def _resolve_questions(
    source: QuestionsSource,
    env: Environment,
    destination: Path,
) -> Sequence[Question]:
    resolved = source(env, destination) if callable(source) else source

    return _validate_questions_sequence(resolved)


def _invoke_apply(
    apply_fn: ApplyCallable,
    *,
    context: ManifestContext,
) -> CreatedPaths:
    result = _invoke_context_hook(apply_fn, context, hook_name="apply")

    return _normalise_apply_result(result)


def _normalise_apply_result(result: object) -> CreatedPaths:
    if result is None:
        return None
    if isinstance(result, (str, Path)):
        return [result]

    if isinstance(result, Sequence) and all(isinstance(item, (str, Path)) for item in result):
        return list(result)

    raise SystemExit("apply() must return None, a path, or a sequence of paths.")


def _invoke_context_hook(
    hook: ApplyCallable | TitleCallable,
    context: ManifestContext,
    *,
    hook_name: str,
) -> CreatedPaths | Path | str | None:
    _validate_context_hook_signature(hook, hook_name)

    return hook(context)


def _validate_context_hook_signature(hook: Callable[..., object], hook_name: str) -> None:
    try:
        signature = inspect.signature(hook)
    except (TypeError, ValueError) as error:
        raise SystemExit(f"failed to inspect {hook_name}(): {error}") from error

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
        raise SystemExit(f"{hook_name}() in sprout.py must accept exactly one parameter: context.")


def _prepare_template_source(template_src: str) -> tuple[Path, Callable[[], None]]:
    candidate = Path(template_src).expanduser()
    if candidate.exists():
        if not candidate.is_dir():
            raise SystemExit(f"template source {template_src} must be a directory.")

        return candidate.resolve(), lambda: None

    url = _normalise_git_url(template_src)
    temp_dir_context = tempfile.TemporaryDirectory(prefix="sprout-template-")
    temp_dir = Path(temp_dir_context.name)
    target_dir = temp_dir / "template"
    git_executable = _resolve_git_executable()

    try:
        subprocess.run(  # noqa: S603 - validated git clone invocation
            [git_executable, "clone", "--depth", "1", "--", url, str(target_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:  # pragma: no cover - external dependency
        temp_dir_context.cleanup()
        stderr = error.stderr.strip() if error.stderr else str(error)
        raise SystemExit(f"failed to clone template from {url}: {stderr}") from error

    return target_dir, temp_dir_context.cleanup


def _resolve_git_executable() -> str:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise SystemExit("git is required to clone remote templates.")

    return git_executable


def _normalise_git_url(template_src: str) -> str:
    cleaned = template_src.strip()
    if cleaned.startswith(("http://", "https://", "git@", "ssh://")):
        return cleaned

    if cleaned.count("/") == 1 and " " not in cleaned:
        owner, repo = cleaned.split("/", maxsplit=1)
        repo_name = repo if repo.endswith(".git") else f"{repo}.git"
        return f"https://github.com/{owner}/{repo_name}"

    return cleaned


def _load_manifest_module(template_dir: Path, manifest_path: Path) -> ModuleType:
    module_name = "sprout_template_manifest"
    spec = importlib.util.spec_from_file_location(module_name, manifest_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"unable to load manifest from {manifest_path}.")

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


def _validate_questions_signature(questions: Callable[..., object]) -> None:
    try:
        signature = inspect.signature(questions)
    except (TypeError, ValueError) as error:
        raise SystemExit(
            "questions callable in sprout.py must accept (env, destination) parameters."
        ) from error

    parameters = tuple(signature.parameters.values())
    allowed_kinds = {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }
    valid_shape = len(parameters) == 2 and all(
        parameter.kind in allowed_kinds for parameter in parameters
    )

    if not valid_shape:
        raise SystemExit(
            "questions callable in sprout.py must accept exactly two positional "
            "parameters: (env, destination)."
        )


def _validate_questions_sequence(value: object) -> Sequence[Question]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise SystemExit("questions must be a sequence of Question instances.")

    questions = list(value)
    if not all(isinstance(question, Question) for question in questions):
        raise SystemExit("each entry in questions must be a Question instance.")

    return questions


def _validate_skip_signature(skip: Callable[..., object]) -> None:
    try:
        signature = inspect.signature(skip)
    except (TypeError, ValueError) as error:
        raise SystemExit(
            "should_skip_file in sprout.py must be a callable with "
            "(relative_path: str, answers) parameters."
        ) from error

    parameters = tuple(signature.parameters.values())
    allowed_kinds = {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }
    valid_shape = len(parameters) == 2 and all(
        parameter.kind in allowed_kinds for parameter in parameters
    )

    if not valid_shape:
        raise SystemExit(
            "should_skip_file in sprout.py must accept exactly two positional "
            "parameters: (relative_path: str, answers)."
        )


def _load_manifest(template_dir: Path) -> Manifest:
    manifest_path = template_dir / "sprout.py"
    if not manifest_path.is_file():
        raise SystemExit(f"template source {template_dir} is missing sprout.py.")

    module = _load_manifest_module(template_dir, manifest_path)
    reader = ManifestReader(vars(module))

    return Manifest(
        questions=reader.questions(),
        apply=reader.apply(),
        template_dir=reader.template_dir(),
        skip=reader.skip(),
        style=reader.style(),
        extensions=reader.extensions(),
        title=reader.title(),
    )


def _display_title(
    title: str | TitleCallable | None,
    *,
    context: ManifestContext,
) -> None:
    if title is None:
        return

    if isinstance(title, str):
        console.print(title)
        return

    result = _invoke_context_hook(title, context, hook_name="title")

    if result is None:
        return

    if not isinstance(result, str):
        raise SystemExit("title() must return a string or None.")

    console.print(result)


def _sanitize_question_key(key: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]", "_", key)
    if not cleaned:
        cleaned = "question"

    if cleaned[0].isdigit():
        cleaned = f"q_{cleaned}"

    return cleaned


_FLAG_ONLY_OPTIONS = {"-h", "--help", "--force"}
_HELP_OPTIONS = {"-h", "--help"}
_HELP_PROBE_DESTINATION = "__sprout_help_destination__"
_HELP_PRELOAD_FALLBACK_NOTE = (
    "Template-specific options could not be resolved from template-only help. "
    "Run sprout <template> <destination> --help for full template-aware options."
)


def _consume_optional_value(args: Sequence[str], index: int) -> int:
    option = args[index]
    if option in _FLAG_ONLY_OPTIONS or "=" in option:
        return index + 1

    next_index = index + 1
    if next_index >= len(args):
        return next_index

    next_arg = args[next_index]
    if next_arg == "--" or next_arg.startswith("-"):
        return index + 1

    return index + 2


def _has_help_option(args: Sequence[str] | None) -> bool:
    if not args:
        return False

    return any(value in _HELP_OPTIONS for value in args)


def _extract_template_destination(
    args: Sequence[str] | None,
) -> tuple[str | None, Path | None]:
    if not args:
        return None, None

    positional: list[str] = []
    end_of_opts = False
    i = 0
    while i < len(args) and len(positional) < 2:
        arg_value = args[i]
        if not end_of_opts and arg_value == "--":
            end_of_opts = True
            i += 1

            continue

        if not end_of_opts and arg_value.startswith("-"):
            i = _consume_optional_value(args, i)
            continue

        positional.append(arg_value)

        i += 1

    template = positional[0] if positional else None
    destination = positional[1] if len(positional) > 1 else None
    if destination is None:
        return template, None

    return template, Path(destination).expanduser().resolve()


def _load_questions_for_cli(template_src: str, destination: Path) -> PreparedTemplate:
    template_dir, cleanup = _prepare_template_source(template_src)
    try:
        manifest = _load_manifest(template_dir)
        actual_template_dir = _resolve_actual_template_dir(template_dir, manifest.template_dir)
        env = build_environment(actual_template_dir, extensions=manifest.extensions or ())
        questions = _resolve_questions(manifest.questions, env, destination)
    except (Exception, SystemExit):
        cleanup()
        raise

    return PreparedTemplate(
        template_src=template_src,
        template_dir=template_dir,
        manifest=manifest,
        cleanup=cleanup,
        questions=questions,
    )


def _prepare_template_for_cli(
    invocation: CLIInvocation,
) -> tuple[PreparedTemplate | None, str | None]:
    if invocation.template_src and invocation.destination is not None:
        return _load_questions_for_cli(invocation.template_src, invocation.destination), None

    if not invocation.template_src or not invocation.help_requested:
        return None, None

    try:
        probe_destination = (Path.cwd() / _HELP_PROBE_DESTINATION).resolve()
        return _load_questions_for_cli(invocation.template_src, probe_destination), None
    except SystemExit:
        return None, _HELP_PRELOAD_FALLBACK_NOTE
    except Exception:  # noqa: BLE001 - help output should not fail on preload errors.
        return None, _HELP_PRELOAD_FALLBACK_NOTE


def _format_question_help(question: Question) -> str:
    description = question.prompt
    if question.help:
        description = f"{description} - {question.help}"

    if question.multiselect:
        description = f"{description} (multiple values allowed)"

    return description


def _flag_from_question_key(key: str) -> str:
    cleaned = key.strip().replace("_", "-")
    cleaned = re.sub(r"[^0-9a-zA-Z-]", "-", cleaned)
    cleaned = cleaned.strip("-")

    return cleaned.lower() or "question"


def _build_cli_parser(
    prepared: PreparedTemplate | None,
    *,
    help_note: str | None = None,
) -> ArgumentParser:
    description = "Generate a project from a sprout manifest."
    if help_note:
        description = f"{description}\n\n{help_note}"
    parser = ArgumentParser(
        prog="sprout",
        description=description,
    )
    parser.add_argument(
        "template",
        help="path or git repository containing a sprout.py manifest",
    )
    parser.add_argument(
        "destination",
        help="target directory for the generated project",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite files in the destination directory if they already exist",
    )

    if prepared is None:
        return parser

    used_dests = {"template", "destination", "force", "help"}
    for question in prepared.questions:
        dest = _sanitize_question_key(question.key)
        if dest in used_dests:
            continue

        used_dests.add(dest)

        flag = f"--{_flag_from_question_key(question.key)}"
        help_text = _format_question_help(question)
        choice_values: list[str] | None = None
        if not callable(question.choices):
            choices = question.resolve_choices({})
            if choices:
                choice_values = [value for value, _label in choices]

        if question.multiselect:
            parser.add_argument(
                flag,
                dest=dest,
                help=help_text,
                default=argparse.SUPPRESS,
                type=str,
                choices=choice_values,
                action="append",
            )
            continue

        parser.add_argument(
            flag,
            dest=dest,
            help=help_text,
            default=argparse.SUPPRESS,
            type=str,
            choices=choice_values,
        )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the CLI entrypoint and return an exit status code.

    Args:
        argv (Sequence[str] | None): Optional argument vector. If None, use `sys.argv[1:]`.

    Raises:
        SystemExit: If argument parsing or template execution fails.
    """
    args_list = list(argv) if argv is not None else None
    inspect_args = args_list if args_list is not None else sys.argv[1:]
    invocation = CLIInvocation.from_args(inspect_args)
    prepared, help_note = _prepare_template_for_cli(invocation)

    parser = _build_cli_parser(prepared, help_note=help_note)
    try:
        parsed, _unknown = parser.parse_known_args(args_list)
        namespace = namespace_to_dict(parsed)
        template = namespace.get("template")
        destination_value = namespace.get("destination")
        force = bool(namespace.get("force", False))
        cli_answers: dict[str, DefaultValue] = {}

        if prepared is not None:
            for question in prepared.questions:
                dest = _sanitize_question_key(question.key)
                if dest in namespace:
                    cli_answers[question.key] = namespace[dest]

        if template is None or destination_value is None:
            raise SystemExit("template and destination are required.")

        return _run_generate(
            template,
            destination_value,
            force=force,
            initial_answers=cli_answers or None,
            prepared=prepared,
        )
    finally:
        if prepared is not None:
            prepared.cleanup()


__all__ = [
    "Manifest",
    "ManifestContext",
    "TemplateCLIArgs",
    "ensure_destination",
    "execute_manifest",
    "generate",
    "main",
    "render_templates",
    "run_template",
    "summarize",
]
