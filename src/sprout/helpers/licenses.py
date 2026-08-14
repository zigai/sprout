from __future__ import annotations

from datetime import UTC, datetime
from string import Template

NO_LICENSE = "None"
UNLICENSED_LICENSE_VALUE = "UNLICENSED"

COMMON_LICENSE_CHOICES: tuple[tuple[str, str], ...] = (
    (NO_LICENSE, "No license"),
    ("MIT", "MIT License"),
    ("Apache-2.0", "Apache License 2.0"),
)

SPDX_LICENSE_CHOICES: tuple[tuple[str, str], ...] = (
    *COMMON_LICENSE_CHOICES,
    ("GPL-3.0", "GNU General Public License v3.0 only"),
    ("BSD-3-Clause", 'BSD 3-Clause "New" or "Revised" License'),
    ("Unlicense", "The Unlicense"),
    ("GPL-2.0", "GNU General Public License v2.0 only"),
    ("AGPL-3.0", "GNU Affero General Public License v3.0"),
    ("LGPL-3.0", "GNU Lesser General Public License v3.0 only"),
    ("LGPL-2.1", "GNU Lesser General Public License v2.1 only"),
    ("BSD-2-Clause", 'BSD 2-Clause "Simplified" License'),
    ("BSD-3-Clause-Clear", "BSD 3-Clause Clear License"),
    ("BSL-1.0", "Boost Software License 1.0"),
    ("CC-BY-4.0", "Creative Commons Attribution 4.0 International"),
    ("CC-BY-SA-4.0", "Creative Commons Attribution Share Alike 4.0"),
    ("CC0-1.0", "Creative Commons Zero v1.0 Universal"),
    ("WTFPL", "Do What The F*ck You Want To Public License"),
    ("AFL-3.0", "Academic Free License v3.0"),
    ("Artistic-2.0", "Artistic License 2.0"),
    ("ECL-2.0", "Educational Community License v2.0"),
    ("EPL-1.0", "Eclipse Public License 1.0"),
    ("EPL-2.0", "Eclipse Public License 2.0"),
    ("EUPL-1.1", "European Union Public License 1.1"),
    ("EUPL-1.2", "European Union Public License 1.2"),
    ("ISC", "ISC License"),
    ("LPPL-1.3c", "LaTeX Project Public License v1.3c"),
    ("MPL-2.0", "Mozilla Public License 2.0"),
    ("MS-PL", "Microsoft Public License"),
    ("MS-RL", "Microsoft Reciprocal License"),
    ("NCSA", "University of Illinois/NCSA Open Source License"),
    ("OFL-1.1", "SIL Open Font License 1.1"),
    ("OSL-3.0", "Open Software License 3.0"),
    ("PostgreSQL", "PostgreSQL License"),
    ("Zlib", "zlib License"),
)

MIT_TEMPLATE = Template(
    "MIT License\n\n"
    "Copyright (c) $year $holder\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
    'of this software and associated documentation files (the "Software"), to deal\n'
    "in the Software without restriction, including without limitation the rights\n"
    "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
    "copies of the Software, and to permit persons to whom the Software is\n"
    "furnished to do so, subject to the following conditions:\n\n"
    "The above copyright notice and this permission notice shall be included in all\n"
    "copies or substantial portions of the Software.\n\n"
    'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\n'
    "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\n"
    "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\n"
    "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\n"
    "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\n"
    "OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\n"
    "SOFTWARE.\n"
)

APACHE_2_TEMPLATE = Template(
    "Apache License\n"
    "Version 2.0, January 2004\n"
    "http://www.apache.org/licenses/\n\n"
    "Copyright $year $holder\n\n"
    'Licensed under the Apache License, Version 2.0 (the "License");\n'
    "you may not use this file except in compliance with the License.\n"
    "You may obtain a copy of the License at\n\n"
    "    http://www.apache.org/licenses/LICENSE-2.0\n\n"
    "Unless required by applicable law or agreed to in writing, software\n"
    'distributed under the License is distributed on an "AS IS" BASIS,\n'
    "WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.\n"
    "See the License for the specific language governing permissions and\n"
    "limitations under the License.\n"
)

LICENSE_TEMPLATES: dict[str, Template] = {
    "Apache-2.0": APACHE_2_TEMPLATE,
    "MIT": MIT_TEMPLATE,
}


def package_license_value(
    license_name: str | None, *, none_value: str = UNLICENSED_LICENSE_VALUE
) -> str:
    selected = NO_LICENSE if not license_name else f"{license_name}"
    return none_value if selected == NO_LICENSE else selected


def should_skip_license_file(
    relative_path: str,
    answers: dict[str, object],
    *,
    license_key: str = "copyright_license",
) -> bool:
    return relative_path == "LICENSE.jinja" and answers.get(license_key) == NO_LICENSE


def render_license_text(
    license_name: str,
    copyright_holder: str,
    *,
    year: int | None = None,
) -> str:
    selected = license_name.strip()
    if selected == NO_LICENSE:
        return ""

    template = LICENSE_TEMPLATES.get(selected)
    if template is None:
        raise ValueError(f"license text is not bundled for {selected}.")

    resolved_year = year if year is not None else datetime.now(tz=UTC).year

    return template.substitute(year=resolved_year, holder=copyright_holder)


__all__ = [
    "COMMON_LICENSE_CHOICES",
    "LICENSE_TEMPLATES",
    "NO_LICENSE",
    "SPDX_LICENSE_CHOICES",
    "UNLICENSED_LICENSE_VALUE",
    "package_license_value",
    "render_license_text",
    "should_skip_license_file",
]
