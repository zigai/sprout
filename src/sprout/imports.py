from __future__ import annotations

import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from types import ModuleType

_import_lock = RLock()
_import_scopes: list[TemplateImports] = []


class TemplateImports:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.modules: dict[str, ModuleType] = {}

    @contextmanager
    def activate(self) -> Generator[None, None, None]:
        with _import_lock:
            if _import_scopes and _import_scopes[-1] is self:
                yield
                return

            before = sys.modules.copy()
            displaced: set[str] = set()
            if _import_scopes:
                previous = _import_scopes[-1]
                TemplateImports._capture(previous)
                displaced = set(previous.modules)
                for name in displaced:
                    sys.modules.pop(name, None)

            sys.modules.update(self.modules)
            _import_scopes.append(self)
            template_path = str(self.root)
            sys.path.insert(0, template_path)
            try:
                yield
            finally:
                self._capture()
                _import_scopes.pop()
                for name in self.modules.keys() | displaced:
                    if name in before:
                        sys.modules[name] = before[name]
                    else:
                        sys.modules.pop(name, None)

                try:
                    sys.path.remove(template_path)
                except ValueError:
                    pass

    def _capture(self) -> None:
        for name, imported in sys.modules.copy().items():
            if not isinstance(imported, ModuleType):
                continue

            file_path = imported.__dict__.get("__file__")
            paths = (file_path,) if file_path else imported.__dict__.get("__path__", ())
            if any(Path(path).absolute().is_relative_to(self.root) for path in paths):
                self.modules[name] = imported


__all__ = ["TemplateImports"]
