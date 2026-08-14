from __future__ import annotations

import pytest

import sprout.extensions.current_year as current_year_module
import sprout.extensions.git_defaults as git_defaults_module
import sprout.helpers.licenses as licenses_module
import sprout.helpers.validators as validators_module
import sprout.manifest as manifest_module
import sprout.prompt.question as question_module
import sprout.prompt.style as style_module
import sprout.renderer as renderer_module
from sprout import (
    NO_LICENSE,
    CurrentYearExtension,
    GitDefaultsExtension,
    ManifestContext,
    Question,
    SproutError,
    SproutGenerationError,
    SproutManifestError,
    SproutPromptError,
    SproutRegistryError,
    SproutScaffoldError,
    SproutTemplateSourceError,
    Style,
    render_templates,
    validate_repository_url,
)


def test_readme_documented_root_imports_resolve_to_owning_modules() -> None:
    assert Question is question_module.Question
    assert validate_repository_url is validators_module.validate_repository_url
    assert NO_LICENSE is licenses_module.NO_LICENSE
    assert CurrentYearExtension is current_year_module.CurrentYearExtension
    assert GitDefaultsExtension is git_defaults_module.GitDefaultsExtension
    assert ManifestContext is manifest_module.ManifestContext
    assert render_templates is renderer_module.render_templates
    assert Style is style_module.Style


@pytest.mark.parametrize(
    "error_type",
    [
        SproutGenerationError,
        SproutManifestError,
        SproutPromptError,
        SproutRegistryError,
        SproutScaffoldError,
        SproutTemplateSourceError,
    ],
)
def test_public_operational_errors_share_one_base(
    error_type: type[SproutError],
) -> None:
    error = error_type("failure")

    assert isinstance(error, SproutError)
    assert error.message == "failure"
    assert str(error) == "failure"
