from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "sprout"
type ImportDetails = tuple[str, tuple[str, ...]]


def _module_name(path: Path) -> str:
    relative_path = path.relative_to(PACKAGE_ROOT).with_suffix("")
    parts: list[str] = list(relative_path.parts)
    if parts[-1] == "__init__":
        del parts[-1]

    return ".".join(("sprout", *parts))


def _package_name(path: Path) -> str:
    module_name = _module_name(path)
    if path.name == "__init__.py":
        return module_name

    return module_name.rpartition(".")[0]


def _resolve_from_module(node: ast.ImportFrom, *, package_name: str) -> str:
    if node.level == 0:
        return node.module or ""

    package_parts: list[str] = package_name.split(".")
    parent_count = node.level - 1
    if parent_count:
        package_parts = package_parts[:-parent_count]

    if node.module:
        package_parts.extend(node.module.split("."))

    return ".".join(package_parts)


def _import_details(
    node: ast.Import | ast.ImportFrom,
    *,
    package_name: str,
) -> tuple[ImportDetails, ...]:
    if isinstance(node, ast.Import):
        return tuple((alias.name, (alias.name,)) for alias in node.names)

    imported_from = _resolve_from_module(node, package_name=package_name)
    targets: list[str] = []
    for alias in node.names:
        if alias.name == "*":
            continue

        targets.append(f"{imported_from}.{alias.name}" if imported_from else alias.name)

    return ((imported_from, tuple(targets)),)


def _import_aliases(
    tree: ast.Module,
    *,
    package_name: str,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.partition(".")[0]
                aliases[local_name] = alias.name

            continue

        if not isinstance(node, ast.ImportFrom):
            continue

        imported_from = _resolve_from_module(node, package_name=package_name)
        for alias in node.names:
            if alias.name == "*":
                continue

            local_name = alias.asname or alias.name
            aliases[local_name] = f"{imported_from}.{alias.name}" if imported_from else alias.name

    return aliases


def _call_name(function: ast.expr, *, aliases: dict[str, str]) -> str:
    if isinstance(function, ast.Name):
        return aliases.get(function.id, function.id)
    if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
        owner = aliases.get(function.value.id, function.value.id)
        return f"{owner}.{function.attr}"

    return ""


def _dynamic_import_details(
    node: ast.Call,
    *,
    aliases: dict[str, str],
) -> tuple[ImportDetails, ...]:
    module_argument = node.args[0] if node.args else None
    if module_argument is None:
        module_argument = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "name"),
            None,
        )

    if not isinstance(module_argument, ast.Constant) or not isinstance(module_argument.value, str):
        return ()

    function_name = _call_name(node.func, aliases=aliases)
    if function_name not in {"__import__", "builtins.__import__", "importlib.import_module"}:
        return ()

    module_name = module_argument.value
    if module_name.startswith("."):
        return ()

    return ((module_name, (module_name,)),)


def _is_module_or_child(module_name: str, expected: str) -> bool:
    return module_name == expected or module_name.startswith(f"{expected}.")


def test_production_dependency_boundaries() -> None:
    violations: list[str] = []

    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        module_name = _module_name(path)
        package_name = _package_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _import_aliases(tree, package_name=package_name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                import_details = _import_details(node, package_name=package_name)
            elif isinstance(node, ast.Call):
                import_details = _dynamic_import_details(node, aliases=aliases)
            else:
                continue

            for imported_from, targets in import_details:
                imported_modules = (imported_from, *targets)
                location = f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}"

                if imported_from == "sprout":
                    violations.append(f"{location}: imports package-root sprout")

                if not _is_module_or_child(module_name, "sprout.cli") and any(
                    _is_module_or_child(imported, "sprout.cli") for imported in imported_modules
                ):
                    violations.append(f"{location}: non-CLI module imports sprout.cli")

                if module_name == "sprout.prompt.processing" and (
                    imported_from == "sprout.prompt"
                    or any(
                        _is_module_or_child(imported, "sprout.prompt.terminal")
                        for imported in imported_modules
                    )
                ):
                    violations.append(f"{location}: prompt.processing imports terminal behavior")

                effective_targets = targets or (imported_from,)
                prompt_targets = tuple(
                    imported
                    for imported in effective_targets
                    if _is_module_or_child(imported, "sprout.prompt")
                )
                imports_disallowed_prompt = bool(prompt_targets) and not all(
                    _is_module_or_child(imported, "sprout.prompt.validation")
                    for imported in prompt_targets
                )
                if _is_module_or_child(module_name, "sprout.helpers") and imports_disallowed_prompt:
                    violations.append(
                        f"{location}: helper imports outside sprout.prompt.validation"
                    )

    assert not violations, "Dependency boundary violations:\n" + "\n".join(violations)
