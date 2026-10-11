from __future__ import annotations

import pytest

from sprout.helpers import (
    COMMON_LICENSE_CHOICES,
    package_license_value,
    render_license_text,
    should_skip_license_file,
)


def test_license_helpers_cover_common_template_cases() -> None:
    assert COMMON_LICENSE_CHOICES[0] == ("None", "No license")
    assert package_license_value("None") == "UNLICENSED"
    assert package_license_value("MIT") == "MIT"
    assert should_skip_license_file("LICENSE.jinja", {"copyright_license": "None"}) is True
    assert should_skip_license_file("README.md.jinja", {"copyright_license": "None"}) is False

    mit_text = render_license_text("MIT", "Zig Author", year=2026)

    assert "MIT License" in mit_text
    assert "Copyright (c) 2026 Zig Author" in mit_text

    apache_text = render_license_text("Apache-2.0", "Zig Author", year=2026)

    assert "Apache License" in apache_text
    assert "Copyright 2026 Zig Author" in apache_text

    with pytest.raises(ValueError, match="not bundled"):
        render_license_text("GPL-3.0", "Zig Author", year=2026)
