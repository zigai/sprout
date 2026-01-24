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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from interfacy.appearance.layouts import InterfacyLayout
from interfacy.argparse_backend.argument_parser import ArgumentParser, namespace_to_dict
from jinja2 import Environment
from jinja2.ext import Extension
from rich.text import Text

from sprout.extensions import build_environment
from sprout.prompt import ask_question, collect_answers, console, supports_live_interaction
from sprout.question import Question
from sprout.style import Style

SkipPredicate = Callable[[str, dict[str, Any]], bool]
QuestionsSource = Sequence[Question] | Callable[[Environment, Path], Sequence[Question]]


@dataclass(frozen=True)
class TemplateCLIArgs:
    template_src: str
    destination: Path
    force: bool = False


@dataclass(frozen=True)
class Manifest:
    questions: QuestionsSource
    apply: Callable[..., Any] | None = None
    template_dir: str | Path | None = None
    skip: SkipPredicate | None = None
    style: Style | None = None
    extensions: Sequence[type[Extension]] | None = None
    title: str | Callable[..., Any] | None = None


@dataclass(frozen=True)
class PreparedTemplate:
    template_src: str
    template_dir: Path
    manifest: Manifest
    cleanup: Callable[[], None]
    questions: Sequence[Question]


def ensure_destination(path: Path, *, force: bool, style: Style | None = None) -> None:
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


def render_templates(
    env: Environment | None,
    template_dir: Path,
    destination: Path,
    answers: dict[str, Any],
    *,
    skip: SkipPredicate | None = None,
    render_paths: bool = False,
    ignore: Sequence[str] | None = None,
    extensions: Sequence[type[Extension]] | None = None,
) -> list[Path]:
    """
    Render a template directory into ``destination``.

    - If ``render_paths`` is True, treat relative paths as Jinja templates and render them with ``answers`` (useful for names like ``"{{ package_name }}"``).
    - ``ignore`` is a list of glob patterns (matched against file name) and special names to skip
    """
    created: list[Path] = []
    ignore = list(ignore or [])
    default_ignore_globs = ["*.pyc", "*.pyo", "*.pyd", "*.swp", "*~", ".DS_Store"]
    for pat in default_ignore_globs:
        if pat not in ignore:
            ignore.append(pat)

    def _ignored(path: Path) -> bool:
        if any(part == "__pycache__" for part in path.parts):
            return True
        name = path.name
        return any(fnmatch.fnmatch(name, pat) for pat in ignore)

    if env is None:
        env = build_environment(template_dir, extensions=extensions or ())

    for source in sorted(template_dir.rglob("*")):
        if source.is_dir():
            continue

        if _ignored(source):
            continue

        relative = source.relative_to(template_dir)
        relative_str = relative.as_posix()
        if skip and skip(relative_str, answers):
            continue

        if render_paths:
            rendered_rel_str = env.from_string(relative.as_posix()).render(**answers)
            target_relative = Path(rendered_rel_str)
            if source.suffix == ".jinja":
                target_relative = target_relative.with_suffix("")
        else:
            target_relative = relative.with_suffix("") if source.suffix == ".jinja" else relative

        target_path = destination / target_relative
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if source.suffix == ".jinja":
            template = env.get_template(relative_str)
            rendered = template.render(**answers)
            target_path.write_text(rendered, encoding="utf-8")
        else:
            shutil.copy2(source, target_path)

        created.append(target_relative)

    return created


def summarize(created: Sequence[Path]) -> None:
    if not created:
        return

    console.print(Text("\nGenerated files", style="white"))
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
    initial_answers: dict[str, Any] | None = None,
    force: bool = False,
    banner: Callable[[], None] | None = None,
    summary: Callable[[Sequence[Path]], None] | None = None,
) -> tuple[dict[str, Any], Sequence[Path]]:
    style = style or Style()
    if banner:
        banner()

    if not template_dir.exists():
        raise SystemExit(f"Template directory not found. Expected {template_dir} to exist.")

    env = build_environment(
        template_dir,
        extensions=(extensions or ()),
    )
    questions = question_builder(env, destination)
    answers = collect_answers(questions, style=style, initial_answers=initial_answers)
    ensure_destination(destination, force=force, style=style)
    created = render_templates(
        env,
        template_dir,
        destination,
        answers,
        skip=skip,
        render_paths=True,
    )

    if not created:
        console.print(Text("No files were generated.", style="yellow"))
        return answers, created

    if summary:
        summary(created)
    else:
        summarize(created)
    return answers, created


def execute_manifest(
    manifest: Manifest,
    *,
    template_dir: Path,
    destination: Path,
    force: bool = False,
    initial_answers: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], Sequence[Path] | None]:
    style = manifest.style or Style()
    template_root = template_dir

    actual_template_dir = _resolve_actual_template_dir(template_root, manifest.template_dir)

    env = build_environment(actual_template_dir, extensions=manifest.extensions or ())

    _display_title(
        manifest.title,
        env=env,
        template_dir=template_root,
        destination=destination,
        style=style,
    )

    questions = _resolve_questions(manifest.questions, env, destination)
    answers = collect_answers(questions, style=style, initial_answers=initial_answers)
    ensure_destination(destination, force=force, style=style)

    if manifest.apply is not None:
        created = _invoke_apply(
            manifest.apply,
            env=env,
            template_dir=actual_template_dir,
            template_root=template_root,
            destination=destination,
            answers=answers,
            style=style,
        )
    else:
        if not actual_template_dir.exists():
            raise SystemExit(
                f"Template directory not found. Expected {actual_template_dir} to exist."
            )
        created = render_templates(
            env,
            actual_template_dir,
            destination,
            answers,
            skip=manifest.skip,
            render_paths=True,
        )

    if created is None:
        return answers, None

    created_paths = _normalise_created(created, destination)
    if not created_paths:
        console.print(Text("No files were generated.", style="yellow"))
    else:
        summarize(created_paths)
    return answers, created_paths


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
    initial_answers: dict[str, Any] | None,
    prepared: PreparedTemplate | None,
) -> int:
    destination_path = Path(destination).expanduser().resolve()
    args = TemplateCLIArgs(
        template_src=template,
        destination=destination_path,
        force=force,
    )
    cleanup: Callable[[], None] | None = None
    use_prepared = prepared is not None and prepared.template_src == template
    try:
        if use_prepared:
            template_dir = prepared.template_dir
            manifest = prepared.manifest
        else:
            template_dir, cleanup, manifest = _resolve_template(args)
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
    if callable(source):
        resolved = source(env, destination)
    else:
        resolved = source

    if not isinstance(resolved, Sequence):
        raise SystemExit("questions must be a sequence of Question instances.")

    questions = list(resolved)
    if not all(isinstance(question, Question) for question in questions):
        raise SystemExit("each entry in questions must be a Question instance.")
    return questions


def _invoke_apply(
    apply_fn: Callable[..., Any],
    *,
    env: Environment,
    template_dir: Path,
    template_root: Path,
    destination: Path,
    answers: dict[str, Any],
    style: Style,
) -> Sequence[Path | str] | None:
    available: dict[str, Any] = {
        "env": env,
        "environment": env,
        "template_dir": template_dir,
        "template": template_dir,
        "template_root": template_root,
        "destination": destination,
        "dest": destination,
        "project_dir": destination,
        "output_dir": destination,
        "answers": answers,
        "context": answers,
        "style": style,
        "console": console,
        "render_templates": render_templates,
    }

    signature = inspect.signature(apply_fn)
    kwargs: dict[str, Any] = {}
    for name in signature.parameters:
        if name in available:
            kwargs[name] = available[name]

    try:
        result = apply_fn(**kwargs)
    except TypeError as error:
        raise SystemExit(f"failed to run apply(): {error}") from error

    if result is None:
        return None
    if isinstance(result, (str, Path)):
        return [result]
    if isinstance(result, Sequence):
        return list(result)
    raise SystemExit("apply() must return None, a path, or a sequence of paths.")


def _prepare_template_source(template_src: str) -> tuple[Path, Callable[[], None]]:
    candidate = Path(template_src).expanduser()
    if candidate.exists():
        if not candidate.is_dir():
            raise SystemExit(f"template source {template_src} must be a directory.")
        return candidate.resolve(), lambda: None

    url = _normalise_git_url(template_src)
    temp_dir = Path(tempfile.mkdtemp(prefix="sprout-template-"))
    target_dir = temp_dir / "template"

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(target_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise SystemExit("git is required to clone remote templates.")
    except subprocess.CalledProcessError as error:  # pragma: no cover - external dependency
        stderr = error.stderr.strip() if error.stderr else str(error)
        raise SystemExit(f"failed to clone template from {url}: {stderr}") from error

    return target_dir, lambda: shutil.rmtree(temp_dir, ignore_errors=True)


def _normalise_git_url(template_src: str) -> str:
    cleaned = template_src.strip()
    if cleaned.startswith(("http://", "https://", "git@", "ssh://")):
        return cleaned
    if cleaned.count("/") == 1 and " " not in cleaned:
        owner, repo = cleaned.split("/", maxsplit=1)
        if repo.endswith(".git"):
            repo_name = repo
        else:
            repo_name = f"{repo}.git"
        return f"https://github.com/{owner}/{repo_name}"
    return cleaned


def _load_manifest(template_dir: Path) -> Manifest:
    manifest_path = template_dir / "sprout.py"
    if not manifest_path.is_file():
        raise SystemExit(f"template source {template_dir} is missing sprout.py.")

    module_name = "sprout_template_manifest"
    spec = importlib.util.spec_from_file_location(module_name, manifest_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"unable to load manifest from {manifest_path}.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys_path_added = False
    try:
        if str(template_dir) not in sys.path:
            sys.path.insert(0, str(template_dir))
            sys_path_added = True
        spec.loader.exec_module(module)
    finally:
        if sys_path_added:
            try:
                sys.path.remove(str(template_dir))
            except ValueError:
                pass
        sys.modules.pop(module_name, None)

    questions = getattr(module, "questions", None)
    apply_fn = getattr(module, "apply", None)

    if questions is None:
        raise SystemExit("sprout.py must define a questions variable.")

    if apply_fn is not None and not callable(apply_fn):
        raise SystemExit("apply in sprout.py must be a callable if provided.")

    style = getattr(module, "style", None)
    if style is not None and not isinstance(style, Style):
        raise SystemExit("style in sprout.py must be an instance of sprout.style.Style.")

    extensions = getattr(module, "extensions", None)
    if extensions is not None:
        if not isinstance(extensions, Sequence):
            raise SystemExit("extensions in sprout.py must be a sequence of Jinja2 extensions.")

        checked: list[type[Extension]] = []
        for extension in extensions:
            if not isinstance(extension, type) or not issubclass(extension, Extension):
                raise SystemExit("each entry in extensions must be a Jinja2 Extension subclass.")
            checked.append(extension)

        extensions = tuple(checked)

    title = getattr(module, "title", None)
    if title is not None and not (isinstance(title, str) or callable(title)):
        raise SystemExit("title in sprout.py must be a string or a callable.")

    manifest_template_dir = getattr(module, "template_dir", None)
    if manifest_template_dir is not None and not isinstance(manifest_template_dir, (str, Path)):
        raise SystemExit("template_dir in sprout.py must be a string or a Path.")

    skip = getattr(module, "should_skip_file", None)
    if skip is not None and not callable(skip):
        raise SystemExit(
            "should_skip_file in sprout.py must be a callable taking (relative_path: str, answers)."
        )

    return Manifest(
        questions=questions,
        apply=apply_fn,
        template_dir=manifest_template_dir,
        skip=skip,
        style=style,
        extensions=extensions,
        title=title,
    )


def _display_title(
    title: str | Callable[..., Any] | None,
    *,
    env: Environment,
    template_dir: Path,
    destination: Path,
    style: Style,
) -> None:
    if title is None:
        return

    if isinstance(title, str):
        console.print(title)
        return

    available: dict[str, Any] = {
        "env": env,
        "environment": env,
        "template_dir": template_dir,
        "template": template_dir,
        "template_root": template_dir,
        "destination": destination,
        "dest": destination,
        "project_dir": destination,
        "output_dir": destination,
        "style": style,
        "console": console,
    }

    signature = inspect.signature(title)
    kwargs: dict[str, Any] = {}
    for name in signature.parameters:
        if name in available:
            kwargs[name] = available[name]

    try:
        result = title(**kwargs)  # type: ignore[misc]
    except TypeError as error:
        raise SystemExit(f"failed to run title(): {error}") from error

    if result is None:
        return
    console.print(result)


def _resolve_template(args: TemplateCLIArgs) -> tuple[Path, Callable[[], None], Manifest]:
    template_dir, cleanup = _prepare_template_source(args.template_src)
    manifest = _load_manifest(template_dir)
    return template_dir, cleanup, manifest


def _sanitize_question_key(key: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]", "_", key)
    if not cleaned:
        cleaned = "question"
    if cleaned[0].isdigit():
        cleaned = f"q_{cleaned}"
    return cleaned


def _extract_template_destination(
    args: Sequence[str] | None,
) -> tuple[str | None, Path | None]:
    if not args:
        return None, None

    template: str | None = None
    destination: str | None = None
    end_of_opts = False
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            end_of_opts = True
            i += 1
            continue

        if not end_of_opts and token.startswith("-"):
            if token in ("-h", "--help", "--force"):
                i += 1
                continue
            if "=" in token:
                i += 1
                continue
            if i + 1 < len(args):
                next_token = args[i + 1]
                if next_token == "--" or next_token.startswith("-"):
                    i += 1
                    continue
                i += 2
                continue
            i += 1
            continue

        if template is None:
            template = token
        elif destination is None:
            destination = token
            break
        i += 1

    if template is None or destination is None:
        return template, None
    return template, Path(destination).expanduser().resolve()


def _load_questions_for_cli(template_src: str, destination: Path) -> PreparedTemplate:
    template_dir, cleanup = _prepare_template_source(template_src)
    try:
        manifest = _load_manifest(template_dir)
        actual_template_dir = _resolve_actual_template_dir(template_dir, manifest.template_dir)
        env = build_environment(actual_template_dir, extensions=manifest.extensions or ())
        questions = _resolve_questions(manifest.questions, env, destination)
    except Exception:
        cleanup()
        raise
    return PreparedTemplate(
        template_src=template_src,
        template_dir=template_dir,
        manifest=manifest,
        cleanup=cleanup,
        questions=questions,
    )


def _format_question_help(question: Question) -> str:
    description = question.prompt
    if question.help:
        description = f"{description} - {question.help}"

    try:
        if callable(question.choices):
            choices = None
        else:
            choices = question.resolve_choices({})
    except Exception:
        choices = None

    if choices:
        values = ", ".join(value for value, _label in choices)
        description = f"{description} (choices: {values})"

    if question.multiselect:
        description = f"{description} (multiple values allowed)"
    return description


def _flag_from_question_key(key: str) -> str:
    cleaned = key.strip().replace("_", "-")
    cleaned = re.sub(r"[^0-9a-zA-Z-]", "-", cleaned)
    cleaned = cleaned.strip("-")
    return cleaned.lower() or "question"


def _build_cli_parser(prepared: PreparedTemplate | None) -> ArgumentParser:
    layout = InterfacyLayout()
    parser = ArgumentParser(
        prog="sprout",
        description="Generate a project from a sprout manifest.",
        help_layout=layout,
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
        kwargs: dict[str, Any] = {
            "dest": dest,
            "help": _format_question_help(question),
            "default": argparse.SUPPRESS,
            "type": str,
        }

        if not callable(question.choices):
            choices = question.resolve_choices({})
            if choices:
                kwargs["choices"] = [value for value, _label in choices]

        if question.multiselect:
            kwargs["action"] = "append"

        parser.add_argument(flag, **kwargs)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else None
    inspect_args = args_list if args_list is not None else sys.argv[1:]
    prepared: PreparedTemplate | None = None

    template_src, destination = _extract_template_destination(inspect_args)
    if template_src and destination is not None:
        prepared = _load_questions_for_cli(template_src, destination)

    parser = _build_cli_parser(prepared)
    try:
        parsed, _unknown = parser.parse_known_args(args_list)
        namespace = namespace_to_dict(parsed)
        template = namespace.get("template")
        destination_value = namespace.get("destination")
        force = bool(namespace.get("force", False))
        cli_answers: dict[str, Any] = {}

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
    "TemplateCLIArgs",
    "Manifest",
    "ensure_destination",
    "generate",
    "render_templates",
    "run_template",
    "execute_manifest",
    "summarize",
    "main",
]
