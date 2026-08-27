"""Guards on ``main.py``, the pygbag entry point.

These exist because pygbag imposes requirements on this one file that nothing
else in the codebase shares, and violating them fails only in the browser -
never locally, and never with an error that points at the cause.

The rules, and what breaks when each is broken:

* **Runtime packages must be imported at top level here.** pygbag decides what
  to install by statically parsing this file's source
  (``aio.pep0723.check_list`` -> ``parse_code``). An import nested inside
  ``piu/app.py`` is invisible to it, so the package is never installed and
  resolves to an empty stub. That surfaces later as
  ``module 'pygame' has no attribute 'init'``, which points nowhere near the
  actual problem.

* **The loop must be async.** pygbag drives frames from the browser's vsync
  and needs a coroutine to yield back to; a synchronous ``while True`` hangs
  the tab.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

MAIN = Path(__file__).resolve().parent.parent / "main.py"


@pytest.fixture(scope="module")
def source() -> str:
    return MAIN.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tree(source: str) -> ast.Module:
    return ast.parse(source)


def top_level_imports(tree: ast.Module) -> set[str]:
    """Module names imported at module scope, as pygbag's parser would see them."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


class TestPackageDeclaration:
    def test_pygame_is_imported_at_top_level(self, tree: ast.Module) -> None:
        assert "pygame" in top_level_imports(tree), (
            "main.py must import pygame at top level even though it does not use "
            "it directly. pygbag parses this file to decide what to install; "
            "without the import, pygame resolves to an empty stub in the browser "
            "and fails as \"module 'pygame' has no attribute 'init'\"."
        )

    def test_the_import_is_marked_as_deliberate(self, source: str) -> None:
        # An unused import is exactly what a linter or a tidy-minded reader
        # deletes. The noqa marker and the comment above it are the defence.
        assert re.search(r"^import pygame\s+# noqa", source, re.MULTILINE), (
            "the pygame import must carry a noqa marker so it is not removed "
            "as unused"
        )

    def test_declares_its_dependencies_in_pep723_metadata(self, source: str) -> None:
        block = re.search(r"^# /// script$.*?^# ///$", source, re.MULTILINE | re.DOTALL)
        assert block, "main.py should carry a PEP 723 script metadata block"
        assert "pygame-ce" in block.group(0)

    def test_every_runtime_dependency_is_imported_here(self, tree: ast.Module) -> None:
        """Each declared runtime dependency must appear as a top-level import.

        Adding a dependency to pyproject.toml without importing it here is the
        same trap as above, just deferred until the package is first used.
        """
        pyproject = (MAIN.parent / "pyproject.toml").read_text(encoding="utf-8")
        block = re.search(r"^dependencies = \[(.*?)\]", pyproject, re.MULTILINE | re.DOTALL)
        assert block, "could not find [project].dependencies in pyproject.toml"

        # "pygame-ce>=2.5" -> import name "pygame"
        distributions = re.findall(r'"([A-Za-z0-9_.-]+)', block.group(1))
        import_names = {
            "pygame-ce": "pygame",
        }

        imported = top_level_imports(tree)
        for dist in distributions:
            expected = import_names.get(dist, dist.replace("-", "_"))
            assert expected in imported, (
                "{!r} is a runtime dependency but {!r} is not imported at the top "
                "of main.py, so pygbag will not install it".format(dist, expected)
            )


class TestAsyncEntry:
    def test_main_is_a_coroutine(self, tree: ast.Module) -> None:
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "main" in functions, "main.py must define main()"
        assert isinstance(functions["main"], ast.AsyncFunctionDef), (
            "main() must be async - pygbag drives frames from the browser's "
            "vsync and needs a coroutine to yield back to"
        )

    def test_module_runs_main_through_asyncio(self, source: str) -> None:
        assert "asyncio.run(main())" in source

    def test_entry_is_not_guarded_by_name_main(self, source: str) -> None:
        # pygbag executes this file through shell.source() rather than as
        # __main__, so a conventional guard would silently never fire.
        assert '__name__ == "__main__"' not in source, (
            "main.py must call asyncio.run(main()) unconditionally; pygbag does "
            "not execute it as __main__"
        )
