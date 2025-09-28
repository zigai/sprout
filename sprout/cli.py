from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import inspect
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment
from jinja2.ext import Extension
from rich.text import Text

from sprout.extensions import build_environment
from sprout.prompt import ask_question, collect_answers, console, supports_live_interaction
from sprout.question import Question
from sprout.style import Style

SkipPredicate = Callable[[Path, dict[str, Any]], bool]
QuestionsSource = Sequence[Question] | Callable[[Environment, Path], Sequence[Question]]


@dataclass(frozen=True)
class TemplateCLIArgs:
    template_src: str
    destination: Path
    force: bool = False


@dataclass(frozen=True)
class Manifest:
    questions: QuestionsSource
    apply: Callable[..., Any]
    style: Style | None = None
    extensions: Sequence[type[Extension]] | None = None
    title: str | Callable[..., Any] | None = None


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
    """Render a template directory into ``destination``.

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
        if skip and skip(relative, answers):
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
            template = env.get_template(relative.as_posix())
            rendered = template.render(**answers)
            target_path.write_text(rendered, encoding="utf-8")
        else:
            shutil.copy2(source, target_path)

        created.append(target_relative)

    return created


def summarize(created: Sequence[Path]) -> None:
    if not created:
        return

    console.print(Text("Generated files", style="bold green"))
    for path in created:
        console.print(Text(f"  • {path}", style="green"))


def run_template(
    *,
    template_dir: Path,
    destination: Path,
    question_builder: Callable[[Environment, Path], Sequence[Question]],
    skip: SkipPredicate | None = None,
    extensions: Sequence[type[Extension]] | None = None,
    style: Style | None = None,
    force: bool = False,
    banner: Callable[[], None] | None = None,
    summary: Callable[[Sequence[Path]], None] | None = None,
) -> tuple[dict[str, Any], Sequence[Path]]:
    style = style or Style()
    if banner:
        banner()

    if not template_dir.exists():
        raise SystemExit(f"template directory not found. Expected {template_dir} to exist.")

    env = build_environment(
        template_dir,
        extensions=(extensions or ()),
    )
    questions = question_builder(env, destination)
    answers = collect_answers(questions, style=style)
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
) -> tuple[dict[str, Any], Sequence[Path] | None]:
    style = manifest.style or Style()
    env = build_environment(template_dir, extensions=manifest.extensions or ())

    _display_title(
        manifest.title,
        env=env,
        template_dir=template_dir,
        destination=destination,
        style=style,
    )

    questions = _resolve_questions(manifest.questions, env, destination)
    answers = collect_answers(questions, style=style)
    ensure_destination(destination, force=force, style=style)

    created = _invoke_apply(
        manifest.apply,
        env=env,
        template_dir=template_dir,
        destination=destination,
        answers=answers,
        style=style,
    )

    if created is None:
        return answers, None

    created_paths = _normalise_created(created, destination)
    if not created_paths:
        console.print(Text("No files were generated.", style="yellow"))
    else:
        summarize(created_paths)
    return answers, created_paths


def parse_cli_args(
    argv: Sequence[str] | None = None,
    *,
    description: str | None = None,
) -> TemplateCLIArgs:
    parser = argparse.ArgumentParser(
        description=description
        or "Generate a project from a sprout manifest (questions + apply function).",
    )
    parser.add_argument(
        "template",
        help="Path or git repository containing a sprout.py manifest.",
    )
    parser.add_argument(
        "destination",
        help="Target directory for the generated project.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite files in the destination directory if they already exist.",
    )
    namespace = parser.parse_args(list(argv) if argv is not None else None)
    destination = Path(namespace.destination).expanduser().resolve()
    return TemplateCLIArgs(
        template_src=namespace.template,
        destination=destination,
        force=namespace.force,
    )


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
    destination: Path,
    answers: dict[str, Any],
    style: Style,
) -> Sequence[Path | str] | None:
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
    if not callable(apply_fn):
        raise SystemExit("sprout.py must define an apply() function.")

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

    return Manifest(
        questions=questions,
        apply=apply_fn,
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_cli_args(argv)
    cleanup: Callable[[], None] | None = None
    try:
        template_dir, cleanup, manifest = _resolve_template(args)
        execute_manifest(
            manifest,
            template_dir=template_dir,
            destination=args.destination,
            force=args.force,
        )
    except KeyboardInterrupt:  # pragma: no cover - interactive
        console.print(Text("Aborted by user.", style="bold red"))
        return 1
    finally:
        if cleanup:
            cleanup()
    return 0


__all__ = [
    "TemplateCLIArgs",
    "Manifest",
    "ensure_destination",
    "parse_cli_args",
    "render_templates",
    "run_template",
    "execute_manifest",
    "summarize",
    "main",
]
