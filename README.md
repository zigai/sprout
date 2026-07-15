# sprout

[![Tests](https://github.com/zigai/sprout/actions/workflows/tests.yml/badge.svg)](https://github.com/zigai/sprout/actions/workflows/tests.yml)
[![PyPI version](https://badge.fury.io/py/sprout-template.svg)](https://badge.fury.io/py/sprout-template)
![Supported versions](https://img.shields.io/badge/python-3.12+-blue.svg)
[![Downloads](https://static.pepy.tech/badge/sprout-template)](https://pepy.tech/project/sprout-template)
[![license](https://img.shields.io/github/license/zigai/sprout.svg)](https://github.com/zigai/sprout/blob/master/LICENSE)

Sprout is a Jinja2-based project generator with a Python manifest.

Instead of configuring prompts in
YAML, you write `sprout.py`:

```python
from sprout import Question

questions = [
    Question(key="project_name", prompt="Project name"),
]
```

That single manifest drives interactive prompts, CLI flags, validation and conditional questions.

Template files go in `template/`. `.jinja` files are rendered, everything else
is copied.

Works with local templates, Git repos, or `owner/repo` GitHub shorthand.

Every question becomes a CLI flag so you can script it too:

```bash
sprout new <template-path> <project-path>
sprout new <template-path> <project-path> --project-name demo
```

## Install

```bash
uv tool install sprout-template
```

## Usage

```bash
sprout init [directory]
sprout add <template-source> [--name <trusted-name>]
sprout list
sprout new <template> <project-path> [--force] [--<question-flag> <value> ...]
```

`new` accepts a local template path, Git URL, `owner/repo` GitHub shorthand, or a trusted name added
with `sprout add`. Pass values for question flags to skip those prompts:

```bash
sprout new <template-path> <project-path> --project-name demo
```

Use `sprout new <template> --help` to show template-specific flags.

### Initialize a template

Create a minimal `sprout.py` and `template/README.md.jinja` scaffold in the current directory:

```bash
sprout init
```

Pass a directory to initialize it elsewhere. Existing scaffold files are never overwritten.

### Trusted templates

Store a reusable name for any supported template source:

```bash
sprout add zigai/python-project-template --name python
sprout new python ./my-project
sprout list
```

## Template structure

The source root must contain `sprout.py`.

The only required name is `questions`.

```python
from sprout import Question

questions = [
    Question(key="project_name", prompt="Project name"),
]
```

Optional names are `template_dir`, `style`, `extensions`, `title`, `cli_boolean_style`,
`should_skip_file(...)`, and `apply(context)`.

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

`key` is the answer dictionary key. It also becomes the CLI flag name.

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
sprout new <template-path> <project-path> --workflow tests --workflow lint
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

By default, yes/no questions are exposed as Boolean CLI flags:

```bash
sprout new <template-path> <project-path> --git-init
sprout new <template-path> <project-path> --no-git-init
```

If a template should use explicit yes/no values instead, opt into that style in `sprout.py`:

```python
cli_boolean_style = "yes-no"
```

Then the CLI accepts values for yes/no questions:

```bash
sprout new <template-path> <project-path> --git-init yes
sprout new <template-path> <project-path> --git-init no
```

## Conditional flow

`when` can be a boolean or a callable that receives the answers collected so far:

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

## Defaults, parsers, and validators

Defaults can be static values or callables. Use `default=""` for a text prompt that should accept
a blank answer.

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

## Skipping files

`should_skip_file` receives a path relative to `template_dir` and the final answers:

```python
from sprout import NO_LICENSE


def should_skip_file(relative_path: str, answers: dict[str, object]) -> bool:
    return relative_path == "LICENSE.jinja" and answers.get("license") == NO_LICENSE
```

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

Most templates should use the default renderer, but you can define `apply(context)` when generation needs
custom file creation, post-processing, or post-generation actions.

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

## Examples

- [python-project-template](https://github.com/zigai/python-project-template).

## License

[MIT License](https://github.com/zigai/sprout/blob/master/LICENSE)
