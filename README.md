# sprout

A Jinja2 project generator with Python-based configuration

## Installation

  ```bash
  uv tool install "git+https://github.com/zigai/sprout.git"
  ```

  ```bash
  pip install "git+https://github.com/zigai/sprout.git"
  ```

## CLI help

Sprout reads template questions and exposes them as CLI flags.

Use `sprout <template> --help` to show template-specific flags with best-effort question resolution.
For destination-aware question resolution, use `sprout <template> <destination> --help`.

Provide answers as flags to skip prompts; those questions won't appear in the TUI.

```text
usage: sprout [-h] [--force] [--<question-flag> <value> ...] template destination

generate a project from a sprout manifest (questions with optional apply)

positional arguments:
  template     path or git repository containing a sprout.py manifest
  destination  target directory for the generated project

options:
  -h, --help   show this help message and exit
  --force      overwrite files in the destination directory if they already exist
  --<question-flag>  answer a template question and skip the prompt
```

## `sprout.py` file

The template repository or directory must contain a file named `sprout.py` at its root.

Define these module-level names:

### `questions` **(required)**

Define **one** of:

* A sequence of `sprout.Question`:

  ```python
  questions: Sequence[sprout.Question]
  ```

* A callable that returns a sequence of `Question`:

  ```python
  from jinja2 import Environment
  from pathlib import Path
  from typing import Sequence

  def questions(env: Environment, destination: Path) -> Sequence[Question]:
      ...
  ```

### Conditional questions

Questions can be conditionally shown with `when`. The condition can be a `bool` or a callable that
receives previously collected answers and returns `True`/`False`.

```python
from sprout import Question

questions = [
    Question(
        key="include_ci",
        prompt="Set up CI?",
        choices=[("yes", "Yes"), ("no", "No")],
        default="yes",
    ),
    Question(
        key="ci_provider",
        prompt="Which CI provider should we use?",
        choices=[("github", "GitHub Actions"), ("gitlab", "GitLab CI")],
        when=lambda answers: answers.get("include_ci") == "yes",
    ),
]
```

Notes:

* Conditions are evaluated in question order, so dependencies should come earlier in the list.
* If a question is skipped by `when`, its key is omitted from `answers`.
* Explicit CLI flags still win; if `--ci-provider` is passed, the value is used even when
  `when` would be false.

### Yes/No questions

Use `Question.yes_no(...)` to avoid manually wiring `choices` and a bool parser.

```python
from sprout import Question

questions = [
    Question.yes_no(
        key="create_github_repo",
        prompt="Create GitHub repository now?",
        default=False,
    ),
]
```

### `template_dir` (optional)

Path to the templates directory. Relative paths resolve from the repository root. Default: `template`.

### `should_skip_file` (optional)

Function to skip rendering or copying specific files. `relative_path` is relative to `template_dir`.

```python
def should_skip_file(relative_path: str, answers: dict[str, Any]) -> bool: ...
```

### `style` (optional)

A `sprout.style.Style` instance to customize prompt appearance.

### `extensions` (optional)

A sequence of Jinja2 `Extension` subclasses to add to the environment.

### `title` (optional)

A string to print before prompting, or a callable that returns a string.

### `apply()` (optional)

Custom generation logic.

* If omitted: sprout renders all files from `template_dir` to the destination, with Jinja rendering enabled for files ending in `.jinja` and for relative paths.
* If provided: the function may request any of these parameters by name: `env`, `template_dir`, `template_root`, `destination`, `answers`, `style`, `console`, `render_templates`.

## Minimal example
```python
from sprout import Question

questions = [
    Question(key="project_name", prompt="Project name"),
]

template_dir = "template"

def should_skip_file(relative_path: str, answers: dict[str, Any]) -> bool:
    if relative_path == "LICENSE.jinja" and answers.get("copyright_license") == "None":
        return True
    return False
```

## Advanced example

See [python-project-template](https://github.com/zigai/python-project-template)

## License

[MIT License](https://github.com/zigai/sprout/blob/master/LICENSE)
