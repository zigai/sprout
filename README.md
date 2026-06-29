# sprout

Sprout is a project scaffolding tool for template authors who want the template logic to live in
Python. Templates use Jinja2 for files, but the manifest is a Python file named `sprout.py`.
That file defines the prompt model, defaults, validation, conditional behavior, optional Jinja
extensions, and any custom generation work.

The command line stays simple:

```bash
sprout <template> <destination>
```

The template decides what else is available.

## Install

As a standalone tool:

```bash
uv tool install "git+https://github.com/zigai/sprout.git"
```

Into the active environment:

```bash
pip install "git+https://github.com/zigai/sprout.git"
```

## Usage

```bash
sprout <template> <destination> [--force] [--<question-flag> <value> ...]
```

`template` can be a local directory, a Git URL, or an `owner/repo` GitHub shorthand. The template
root must contain a `sprout.py` manifest.

Minimal examples:

```bash
sprout ./template-repo ./new-project
sprout ./template-repo ./new-project --project-name demo
```

Sprout reads template questions and exposes them as CLI flags. Provide answers as flags to skip
interactive prompts for those questions. Repeat a multiselect flag to pass more than one value.

Base CLI help:

```text
usage: sprout [--help] [--force] TEMPLATE DESTINATION

Generate a project from a sprout manifest.

positional arguments:
  TEMPLATE     path or git repository containing a sprout.py manifest
  DESTINATION  target directory for the generated project

options:
  --help                        Show this help message and exit
  --force                       overwrite files in the destination directory
                                if they already exist
```

Use `sprout <template> --help` to show template-specific flags with best-effort question resolution.
For destination-aware question resolution, use `sprout <template> <destination> --help`.

## Template contract

The source root must contain `sprout.py`.

```text
template-repo/
  sprout.py
  template/
    README.md.jinja
    pyproject.toml.jinja
```

The only required name is `questions`.

```python
from sprout import Question

questions = [
    Question(key="project_name", prompt="Project name"),
]
```

Optional names are `template_dir`, `style`, `extensions`, `title`, `should_skip_file(...)`, and
`apply(context)`.

## Question model

Each `Question` describes one answer:

```python
from sprout import Question

Question(
    key="project_name",
    prompt="Project name",
    help="Used for package metadata and generated paths",
    default="demo",
)
```

`key` is the answer dictionary key. It also becomes the CLI flag name after underscores are replaced
with dashes:

```text
project_name -> --project-name
```

## Choices

Use choices when the answer should come from a closed list:

```python
from sprout import Question

questions = [
    Question(
        key="package_manager",
        prompt="Package manager",
        choices=[("uv", "uv"), ("pip", "pip")],
        default="uv",
    ),
]
```

Static choices are enforced by the generated CLI parser. Dynamic choices are resolved during the
question flow.

## Multiselect

```python
from sprout import Question

questions = [
    Question(
        key="workflow",
        prompt="Workflows",
        choices=[("tests", "Tests"), ("lint", "Lint")],
        multiselect=True,
    ),
]
```

From the CLI:

```bash
sprout ./template-repo ./new-project --workflow tests --workflow lint
```

## Booleans

Use the built-in yes/no helper:

```python
from sprout import Question

questions = [
    Question.yes_no(
        key="git_init",
        prompt="Initialize Git?",
        default=True,
    ),
]
```

Accepted text includes yes/no style answers. The stored value is a boolean.

## Conditional flow

`when` may be a boolean or a callable that receives the answers collected so far:

```python
from sprout import Question

questions = [
    Question.yes_no(
        key="create_github_repo",
        prompt="Create GitHub repository?",
        default=False,
    ),
    Question(
        key="github_repo_visibility",
        prompt="GitHub repository visibility",
        choices=[("private", "Private"), ("public", "Public")],
        default="private",
        when=lambda answers: bool(answers.get("create_github_repo")),
    ),
]
```

Put dependency questions first. Skipped questions are omitted from `answers`. If the caller provides
an explicit CLI flag, that value is still used.

## Defaults, parsers, and validators

Defaults may be static values or callables:

```python
from sprout import Question

questions = [
    Question(
        key="package_name",
        prompt="Package name",
        default=lambda answers: str(answers["project_name"]).replace("-", "_"),
    ),
]
```

Validators return `(valid, message)`:

```python
from sprout import Question, validate_repository_url

questions = [
    Question(
        key="repository_url",
        prompt="Repository URL",
        validators=[validate_repository_url],
    ),
]
```

Sprout includes validators for repository URLs, GitHub repository URLs, repository names, npm package
names, and semantic versions.

## Destination-aware questions

When question definitions need runtime context, make `questions` callable:

```python
from pathlib import Path

from jinja2 import Environment

from sprout import Question


def questions(env: Environment, destination: Path) -> list[Question]:
    return [
        Question(
            key="project_name",
            prompt="Project name",
            default=destination.name,
        ),
    ]
```

The callable must accept exactly two positional parameters: `env` and `destination`.

## Rendering

Default rendering uses `template_dir`, or `template` when no directory is declared.

```python
template_dir = "template"
```

Files ending in `.jinja` are rendered with Jinja and written without the `.jinja` suffix. Other
files are copied as-is. Relative paths are rendered too, so answers can shape generated directories
and filenames.

## Skipping files

`should_skip_file` receives a path relative to `template_dir` and the final answers:

```python
from sprout import NO_LICENSE


def should_skip_file(relative_path: str, answers: dict[str, object]) -> bool:
    return relative_path == "LICENSE.jinja" and answers.get("license") == NO_LICENSE
```

Use this for optional files that can still live in the same template tree.

## Jinja environment

Set Jinja2 extension classes with `extensions`:

```python
from sprout import CurrentYearExtension, GitDefaultsExtension

extensions = [GitDefaultsExtension, CurrentYearExtension]
```

When `extensions` is omitted, the default environment includes Git defaults:

- `git_user_name`
- `git_user_email`
- `github_username`

Include `GitDefaultsExtension` explicitly when you provide a custom extension list and still want
those globals.

`CurrentYearExtension` exposes:

- `current_year`

## Prompt title and style

```python
title = "Generate a Python package"
```

```python
from sprout import ManifestContext


def title(context: ManifestContext) -> str | None:
    return f"Generate project in {context.destination}"
```

The title is evaluated before answers are collected. For prompt appearance, assign `style` to a
`sprout.Style` instance.

## Custom generation

Most templates should use the default renderer. Define `apply(context)` only when generation needs
custom file creation, post-processing, or post-generation actions.

If you still want the default renderer inside `apply`, call `render_templates(...)`:

```python
from sprout import ManifestContext, render_templates


def apply(context: ManifestContext):
    return render_templates(
        context.env,
        context.template_dir,
        context.destination,
        context.answers,
        render_paths=True,
    )
```

`apply` must accept exactly one `context` parameter. It may return `None`, one path, or a sequence of
paths for the generated-files summary.

## Example template

See [python-project-template](https://github.com/zigai/python-project-template).

## License

[MIT License](https://github.com/zigai/sprout/blob/master/LICENSE)
