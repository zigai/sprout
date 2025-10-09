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

```text
usage: sprout [-h] [--force] template destination

generate a project from a sprout manifest (questions with optional apply)

positional arguments:
  template     path or git repository containing a sprout.py manifest
  destination  target directory for the generated project

options:
  -h, --help   show this help message and exit
  --force      overwrite files in the destination directory if they already exist
```

Use “define” instead of “accepts.” Here’s a clean spec that treats them as module-level names you must define in `sprout.py`.

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
