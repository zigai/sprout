from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest
from jinja2 import Environment
from jinja2.ext import Extension

from sprout.cli import ManifestReader, _load_manifest, _load_manifest_module, _resolve_questions
from sprout.question import Question
from sprout.style import Style
from tests.conftest import TemplateFactory


class DummyExtension(Extension):
    pass


def test_manifest_questions_is_required() -> None:
    module = ModuleType("manifest_module")

    with pytest.raises(SystemExit, match="must define a questions variable"):
        ManifestReader(vars(module)).questions()


def test_manifest_questions_rejects_invalid_types() -> None:
    module = ModuleType("manifest_module")

    module.questions = 123

    with pytest.raises(SystemExit, match="must be a sequence or a callable"):
        ManifestReader(vars(module)).questions()

    module.questions = "not-a-sequence-of-questions"

    with pytest.raises(SystemExit, match="must be a sequence or a callable"):
        ManifestReader(vars(module)).questions()


def test_manifest_questions_callable_signature_validation() -> None:
    module = ModuleType("manifest_module")

    def questions() -> list[Question]:
        return []

    module.questions = questions

    with pytest.raises(SystemExit, match="must accept exactly two positional"):
        ManifestReader(vars(module)).questions()

    def valid_questions(_env: Environment, _destination: Path) -> list[Question]:
        return [Question(key="name", prompt="Name")]

    module.questions = valid_questions
    resolved = ManifestReader(vars(module)).questions()
    assert callable(resolved)


def test_manifest_apply_must_be_callable() -> None:
    module = ModuleType("manifest_module")
    module.apply = "nope"

    with pytest.raises(SystemExit, match=r"apply in sprout\.py must be a callable"):
        ManifestReader(vars(module)).apply()


def test_manifest_style_must_be_style_instance() -> None:
    module = ModuleType("manifest_module")
    module.style = "nope"

    with pytest.raises(SystemExit, match=r"must be an instance of sprout\.style\.Style"):
        ManifestReader(vars(module)).style()


def test_manifest_extensions_validation() -> None:
    module = ModuleType("manifest_module")
    module.extensions = 5

    with pytest.raises(SystemExit, match="must be a sequence of Jinja2 extensions"):
        ManifestReader(vars(module)).extensions()

    module.extensions = "nope"

    with pytest.raises(SystemExit, match="must be a sequence of Jinja2 extensions"):
        ManifestReader(vars(module)).extensions()

    module.extensions = [object]

    with pytest.raises(SystemExit, match="must be a Jinja2 Extension subclass"):
        ManifestReader(vars(module)).extensions()

    module.extensions = [DummyExtension]
    assert ManifestReader(vars(module)).extensions() == (DummyExtension,)


def test_manifest_title_validation() -> None:
    module = ModuleType("manifest_module")
    module.title = 123

    with pytest.raises(SystemExit, match="must be a string or a callable"):
        ManifestReader(vars(module)).title()


def test_manifest_template_dir_validation() -> None:
    module = ModuleType("manifest_module")
    module.template_dir = 123

    with pytest.raises(SystemExit, match="must be a string or a Path"):
        ManifestReader(vars(module)).template_dir()


def test_manifest_cli_boolean_style_defaults_to_flags() -> None:
    module = ModuleType("manifest_module")

    assert ManifestReader(vars(module)).cli_boolean_style() == "flags"


def test_manifest_cli_boolean_style_validation() -> None:
    module = ModuleType("manifest_module")
    module.cli_boolean_style = "yes-no"
    assert ManifestReader(vars(module)).cli_boolean_style() == "yes-no"

    module.cli_boolean_style = "both"
    with pytest.raises(SystemExit, match="must be 'flags' or 'yes-no'"):
        ManifestReader(vars(module)).cli_boolean_style()


def test_resolve_questions_validates_shape() -> None:
    env = Environment()
    destination = Path()

    with pytest.raises(SystemExit, match="questions must be a sequence"):
        _resolve_questions(lambda _env, _dest: 123, env, destination)

    with pytest.raises(SystemExit, match="must be a Question instance"):
        _resolve_questions([object()], env, destination)

    resolved = _resolve_questions(
        [Question(key="name", prompt="Name")],
        env,
        destination,
    )
    assert [question.key for question in resolved] == ["name"]


def test_load_manifest_requires_sprout_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match=r"is missing sprout\.py"):
        _load_manifest(tmp_path)


def test_load_manifest_module_supports_local_imports(tmp_path: Path) -> None:
    root = tmp_path / "template"
    root.mkdir()
    (root / "helper.py").write_text("VALUE = 42\n", encoding="utf-8")
    manifest_path = root / "sprout.py"
    manifest_path.write_text(
        "from helper import VALUE\nquestions = []\nloaded_value = VALUE\n",
        encoding="utf-8",
    )

    module = _load_manifest_module(root, manifest_path)

    assert module.loaded_value == 42
    assert "sprout_template_manifest" not in sys.modules
    assert str(root) not in sys.path


def test_load_manifest_happy_path(make_template: TemplateFactory) -> None:
    template_root = make_template(
        """
        from sprout import Question, Style

        questions = [Question(key="name", prompt="Name")]
        style = Style()
        template_dir = "template"
        cli_boolean_style = "yes-no"

        def should_skip_file(relative_path, answers):
            return False
        """
    )

    manifest = _load_manifest(template_root)

    assert manifest.style is not None
    assert isinstance(manifest.style, Style)
    assert manifest.template_dir == "template"
    assert manifest.cli_boolean_style == "yes-no"
    assert manifest.skip is not None
    assert not manifest.skip("README.md.jinja", {})


def test_load_manifest_rejects_invalid_apply(make_template: TemplateFactory) -> None:
    template_root = make_template(
        """
        from sprout import Question

        questions = [Question(key="name", prompt="Name")]
        apply = 5
        """
    )

    with pytest.raises(SystemExit, match=r"apply in sprout\.py must be a callable"):
        _load_manifest(template_root)
