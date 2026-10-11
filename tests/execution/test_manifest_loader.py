from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest
from jinja2 import Environment
from jinja2.ext import Extension

from sprout.cli.app import main
from sprout.errors import SproutManifestError
from sprout.execution import execute_manifest
from sprout.manifest_loader import (
    ManifestReader,
    load_manifest,
    load_manifest_module,
    resolve_questions,
)
from sprout.prompt.question import Question
from sprout.prompt.style import Style
from tests.support.template_factory import TemplateFactory


class DummyExtension(Extension):
    pass


def test_manifest_questions_is_required() -> None:
    module = ModuleType("manifest_module")

    with pytest.raises(SproutManifestError, match="must define a questions variable"):
        ManifestReader(vars(module)).questions()


def test_manifest_questions_rejects_invalid_types() -> None:
    module = ModuleType("manifest_module")

    module.questions = 123

    with pytest.raises(SproutManifestError, match="must be a sequence or a callable"):
        ManifestReader(vars(module)).questions()

    module.questions = "not-a-sequence-of-questions"

    with pytest.raises(SproutManifestError, match="must be a sequence or a callable"):
        ManifestReader(vars(module)).questions()


def test_manifest_questions_callable_signature_validation() -> None:
    module = ModuleType("manifest_module")

    def questions() -> list[Question]:
        return []

    module.questions = questions

    with pytest.raises(SproutManifestError, match="must accept exactly two positional"):
        ManifestReader(vars(module)).questions()

    def valid_questions(_env: Environment, _destination: Path) -> list[Question]:
        return [Question(key="name", prompt="Name")]

    module.questions = valid_questions
    resolved = ManifestReader(vars(module)).questions()
    assert callable(resolved)


def test_manifest_apply_must_be_callable() -> None:
    module = ModuleType("manifest_module")
    module.apply = "nope"

    with pytest.raises(SproutManifestError, match=r"apply in sprout\.py must be a callable"):
        ManifestReader(vars(module)).apply()


def test_manifest_style_must_be_style_instance() -> None:
    module = ModuleType("manifest_module")
    module.style = "nope"

    with pytest.raises(SproutManifestError, match=r"must be an instance of sprout\.Style"):
        ManifestReader(vars(module)).style()


def test_manifest_extensions_validation() -> None:
    module = ModuleType("manifest_module")
    module.extensions = 5

    with pytest.raises(SproutManifestError, match="must be a sequence of Jinja2 extensions"):
        ManifestReader(vars(module)).extensions()

    module.extensions = "nope"

    with pytest.raises(SproutManifestError, match="must be a sequence of Jinja2 extensions"):
        ManifestReader(vars(module)).extensions()

    module.extensions = [object]

    with pytest.raises(SproutManifestError, match="must be a Jinja2 Extension subclass"):
        ManifestReader(vars(module)).extensions()

    module.extensions = [DummyExtension]
    assert ManifestReader(vars(module)).extensions() == (DummyExtension,)


def test_manifest_title_validation() -> None:
    module = ModuleType("manifest_module")
    module.title = 123

    with pytest.raises(SproutManifestError, match="must be a string or a callable"):
        ManifestReader(vars(module)).title()


def test_manifest_template_dir_validation() -> None:
    module = ModuleType("manifest_module")
    module.template_dir = 123

    with pytest.raises(SproutManifestError, match="must be a string or a Path"):
        ManifestReader(vars(module)).template_dir()


def test_manifest_cli_boolean_style_defaults_to_flags() -> None:
    module = ModuleType("manifest_module")

    assert ManifestReader(vars(module)).cli_boolean_style() == "flags"


def test_manifest_cli_boolean_style_validation() -> None:
    module = ModuleType("manifest_module")
    module.cli_boolean_style = "yes-no"
    assert ManifestReader(vars(module)).cli_boolean_style() == "yes-no"

    module.cli_boolean_style = "both"

    with pytest.raises(SproutManifestError, match="must be 'flags' or 'yes-no'"):
        ManifestReader(vars(module)).cli_boolean_style()


def test_resolve_questions_validates_shape() -> None:
    env = Environment()
    destination = Path()

    with pytest.raises(SproutManifestError, match="questions must be a sequence"):
        resolve_questions(lambda _env, _dest: 123, env, destination)

    with pytest.raises(SproutManifestError, match="must be a Question instance"):
        resolve_questions([object()], env, destination)

    resolved = resolve_questions(
        [Question(key="name", prompt="Name")],
        env,
        destination,
    )
    assert [question.key for question in resolved] == ["name"]


def test_load_manifest_requires_sprout_file(tmp_path: Path) -> None:
    with pytest.raises(SproutManifestError, match=r"is missing sprout\.py"):
        load_manifest(tmp_path)


def test_load_manifest_module_supports_local_imports(tmp_path: Path) -> None:
    root = tmp_path / "template"
    root.mkdir()
    (root / "helper.py").write_text("VALUE = 42\n", encoding="utf-8")
    manifest_path = root / "sprout.py"
    manifest_path.write_text(
        "from helper import VALUE\nquestions = []\nloaded_value = VALUE\n",
        encoding="utf-8",
    )

    module = load_manifest_module(root, manifest_path)

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

    manifest = load_manifest(template_root)

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

    with pytest.raises(SproutManifestError, match=r"apply in sprout\.py must be a callable"):
        load_manifest(template_root)


def test_main_isolates_local_imports_between_templates(
    make_template: TemplateFactory,
    tmp_path: Path,
) -> None:
    manifest = """
        from project_defaults import value

        questions = []

        def apply(context):
            target = context.destination / "result.txt"
            target.write_text(value, encoding="utf-8")
            return [target]
    """
    first = make_template(manifest, files={"project_defaults.py": "value = 'first'\n"})
    second = make_template(manifest, files={"project_defaults.py": "value = 'second'\n"})
    first_destination = tmp_path / "first"
    second_destination = tmp_path / "second"

    assert main(["new", str(first), str(first_destination)]) == 0
    assert main(["new", str(second), str(second_destination)]) == 0

    assert (first_destination / "result.txt").read_text(encoding="utf-8") == "first"
    assert (second_destination / "result.txt").read_text(encoding="utf-8") == "second"


@pytest.mark.parametrize("deferred", [False, True], ids=["sequential", "interleaved"])
def test_template_isolates_lazy_package_imports(
    make_template: TemplateFactory,
    tmp_path: Path,
    deferred: bool,
) -> None:
    manifest = """
        from local_helpers import get_value

        questions = []

        def apply(context):
            target = context.destination / "result.txt"
            target.write_text(get_value(), encoding="utf-8")
            return [target]
    """
    helper = """
        def get_value():
            from .settings import value
            return value
    """
    first = make_template(
        manifest,
        files={
            "local_helpers/__init__.py": helper,
            "local_helpers/settings.py": "value = 'first'\n",
        },
    )
    second = make_template(
        manifest,
        files={
            "local_helpers/__init__.py": helper,
            "local_helpers/settings.py": "value = 'second'\n",
        },
    )
    first_destination = tmp_path / "first"
    second_destination = tmp_path / "second"

    if deferred:
        prepared = load_manifest(first)
        load_manifest(second)
        execute_manifest(prepared, template_dir=first, destination=first_destination)
    else:
        assert main(["new", str(first), str(first_destination)]) == 0
        assert main(["new", str(second), str(second_destination)]) == 0
        assert (second_destination / "result.txt").read_text(encoding="utf-8") == "second"

    assert (first_destination / "result.txt").read_text(encoding="utf-8") == "first"


@pytest.mark.parametrize("first_helper", ["local_helpers", "outer_helpers"])
def test_nested_generation_keeps_each_templates_imports(
    make_template: TemplateFactory,
    tmp_path: Path,
    first_helper: str,
) -> None:
    helper = """
        value = "initial"

        def get_value():
            from .settings import value
            return value
    """
    second = make_template(
        """
        import local_helpers as helpers

        questions = []

        def apply(context):
            helpers.value = "second"
            target = context.destination / "result.txt"
            target.write_text(helpers.get_value(), encoding="utf-8")
            return [target]
        """,
        files={
            "local_helpers/__init__.py": helper,
            "local_helpers/settings.py": "from . import value\n",
        },
    )
    first = make_template(
        f"""
        import {first_helper} as helpers
        from sprout.cli.commands import generate

        questions = []

        def apply(context):
            helpers.value = "first"
            generate({str(second)!r}, context.destination / "child")
            target = context.destination / "result.txt"
            target.write_text(helpers.get_value(), encoding="utf-8")
            return [target]
        """,
        files={
            f"{first_helper}/__init__.py": helper,
            f"{first_helper}/settings.py": "from . import value\n",
        },
    )
    destination = tmp_path / "generated"

    assert main(["new", str(first), str(destination)]) == 0

    assert (destination / "result.txt").read_text(encoding="utf-8") == "first"
    assert (destination / "child" / "result.txt").read_text(encoding="utf-8") == "second"
