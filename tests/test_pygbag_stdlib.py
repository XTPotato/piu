"""Every module the game imports must exist in pygbag's trimmed CPython.

This is a guard on a whole class of bug rather than a single instance. The
browser runtime ships a reduced standard library, and a module that is missing
there fails with ``ModuleNotFoundError`` *at first import* - which, for a
lazily-imported screen, lands in front of a player long after boot.

The desktop interpreter has everything, so nothing else in this suite can see
the problem. It has already happened three times in different disguises:

1. ``pygame.K_a`` read at module scope, before pygame was populated.
2. ``pygame`` never installed, because pygbag only scans main.py for imports.
3. ``import statistics`` - ordinary, pure-python, and simply not shipped.

The available-module list is captured from the runtime's own file manifest by
``tools/probe_stdlib.py``. Regenerate it when the pinned pygbag version
changes.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "piu"
ENTRY = ROOT / "main.py"
FIXTURE = Path(__file__).parent / "fixtures" / "pygbag_stdlib.txt"


@pytest.fixture(scope="module")
def available() -> set[str]:
    if not FIXTURE.is_file():
        pytest.fail(
            "missing {}; regenerate with `python tools/probe_stdlib.py`".format(FIXTURE)
        )
    return {
        line.strip()
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def shipped_sources() -> list[Path]:
    """Files that end up in the browser bundle.

    tests/ and tools/ are excluded from the bundle by pygbag.ini and run only
    on the desktop, so their imports are unconstrained.
    """
    return [ENTRY, *sorted(PACKAGE.rglob("*.py"))]


def imported_modules(path: Path) -> set[str]:
    """Top-level module names imported by ``path``, at any nesting depth.

    Function-level imports count: a lazily-imported module missing from the
    runtime fails later and more confusingly than one imported at the top.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # Relative imports are our own package, not external.
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def test_the_fixture_looks_sane(available: set[str]) -> None:
    assert len(available) > 100, "module list is suspiciously short"
    assert "json" in available
    assert "asyncio" in available
    # The module whose absence prompted all of this. If a future pygbag ships
    # it, this test failing is the signal that the workaround can be dropped.
    assert "statistics" not in available, (
        "pygbag now ships statistics; piu/gameplay/offsets.py can drop its "
        "local mean/median/stdev helpers"
    )


@pytest.mark.parametrize(
    "source", shipped_sources(), ids=lambda p: str(p.relative_to(ROOT)).replace("\\", "/")
)
def test_every_import_exists_in_the_browser_runtime(
    source: Path, available: set[str]
) -> None:
    missing = sorted(
        name
        for name in imported_modules(source)
        # Our own package is bundled, so it is always importable.
        if name != "piu" and name not in available
    )
    assert not missing, (
        "{} imports {}, which pygbag's CPython does not ship. The game will "
        "raise ModuleNotFoundError in the browser at first import. Either "
        "avoid the module, or - if it really is available - add it to "
        "ALWAYS_AVAILABLE in tools/probe_stdlib.py and regenerate.".format(
            source.relative_to(ROOT), ", ".join(repr(m) for m in missing)
        )
    )


def test_offsets_does_not_import_statistics() -> None:
    # Pinned specifically, because reaching for statistics.fmean is the
    # natural thing to write here and it works perfectly on the desktop.
    offsets = PACKAGE / "gameplay" / "offsets.py"
    assert "statistics" not in imported_modules(offsets)


def test_stdlib_names_are_real_modules(available: set[str]) -> None:
    """Sanity-check the fixture against this interpreter.

    Everything the browser ships should also exist in desktop CPython. A name
    here that does not resolve locally means the manifest scrape picked up
    something that is not a module.
    """
    import importlib.util

    # Names that genuinely exist in the browser runtime but not in desktop
    # CPython on every host. Not scrape errors:
    #   posix       - a builtin under emscripten and Unix, absent on Windows
    #   _sysconfig* - the emscripten build's own generated config module
    platform_specific = {"posix"}

    suspicious = []
    for name in sorted(available):
        # Runtime-provided names exist only in the browser.
        if name in {"embed", "aio", "pygame", "platform"}:
            continue
        if name in sys.builtin_module_names or name in platform_specific:
            continue
        if name.startswith("_sysconfigdata"):
            continue
        try:
            if importlib.util.find_spec(name) is None:
                suspicious.append(name)
        except (ImportError, ValueError):
            suspicious.append(name)

    assert not suspicious, (
        "these entries do not resolve as modules in desktop CPython, so the "
        "manifest scrape in tools/probe_stdlib.py may be picking up stray "
        "paths: {}".format(", ".join(suspicious))
    )
