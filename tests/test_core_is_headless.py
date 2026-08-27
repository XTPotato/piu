"""Guards the rule that makes the engine core testable.

`piu.core`, `piu.formats`, `piu.gameplay` and `piu.content` hold the timing math, chart
parsing, judgment, and scoring - the parts that must be verifiable without a
display or an audio device. If pygame ever leaks into them, that verifiability
goes away quietly. This test makes it fail loudly instead.
"""

from __future__ import annotations

import subprocess
import sys

HEADLESS_PACKAGES = ("piu.core", "piu.formats", "piu.gameplay", "piu.content")

# Run in a subprocess: by the time this test executes, another test may already
# have imported pygame, which would mask the leak in this interpreter.
# Every submodule is imported, not just the package root, since a package
# __init__ that stays empty would otherwise make this check vacuous.
PROBE = """
import importlib
import pkgutil
import sys

for name in {packages!r}:
    package = importlib.import_module(name)
    for info in pkgutil.walk_packages(package.__path__, name + "."):
        importlib.import_module(info.name)

leaked = sorted(m for m in sys.modules if m == "pygame" or m.startswith("pygame."))
print(",".join(leaked))
"""


def test_engine_core_does_not_import_pygame() -> None:
    result = subprocess.run(
        [sys.executable, "-c", PROBE.format(packages=list(HEADLESS_PACKAGES))],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        "probe failed to import the headless packages:\n" + result.stderr
    )

    leaked = [name for name in result.stdout.strip().split(",") if name]
    assert not leaked, (
        "pygame leaked into the headless engine core via {}.\n"
        "Move display, input, or audio-device code into piu.render, piu.input, "
        "or piu.screens.".format(", ".join(leaked))
    )
