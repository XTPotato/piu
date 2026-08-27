# piu

A 5-panel, upward-scrolling rhythm game in the style of Andamiro's *Pump It Up*,
compiled to WebAssembly and played in the browser.

## What this is

An original reimplementation of the *gameplay* — five panels (Down-Left, Up-Left,
Center, Up-Right, Down-Right), notes that scroll **upward** into a step zone at the
top of the screen, Perfect / Great / Good / Bad / Miss judgment, combo, lifebar, and
graded results.

It loads charts in three formats:

| Format | Notes |
|---|---|
| StepMania `.sm` / `.ssc` | `pump-single`, `pump-halfdouble`, `pump-double`, `pump-routine` |
| Andamiro `.ucs` | Block-structured user charts |
| Native JSON | The canonical model, used for demo charts and test fixtures |

## What this is not

This project ships **no Andamiro content**. No official sprites, logos, fonts, songs,
or step charts are included in this repository or served from the deployed site, and
none will be accepted into it. Publishing to the public web makes that rule sharper,
not softer.

Songs come from two places:

- **Bundled** — originally-authored demo charts over permissively-licensed OGG audio,
  packaged into the build so the site is playable the moment it loads.
- **Fetched** — additional songs served as static files alongside the build and pulled
  on demand when selected.

## The browser is the target

The only shipped artifact is the web build. Running natively is a development
convenience — it iterates faster than a WASM rebuild — but **no timing decision is
ever made outside the browser**, because that is the runtime players actually get.

This shapes the code in three ways worth knowing before you read it:

1. **The game loop is a coroutine.** pygbag drives frames from the browser's vsync,
   and the Python side must yield with `await asyncio.sleep(0)` once per frame or the
   tab hangs. `App.run` in [piu/app.py](piu/app.py) is async, and so is every screen.
2. **Audio comes from the Web Audio API**, not a native library. `sounddevice` (CFFI →
   PortAudio) and `miniaudio` (C extension) have no Emscripten build, so the song
   clock reads `AudioContext.currentTime`. That is a better clock anyway: same
   hardware source as the output, monotonic, and `outputLatency` gives the exact
   correction a native stream-latency subtraction would.
3. **Nothing audible happens before a user gesture.** Browsers refuse to start an
   `AudioContext` otherwise, so the boot screen's click-to-start gate is load-bearing.

The whole browser-facing surface is confined to [piu/runtime.py](piu/runtime.py),
so pygbag's pre-1.0 API churn has a small blast radius.

## Setup

Requires Python 3.12 — the version pygbag's WASM runtime uses. Everything runs inside
a project-local virtual environment; nothing is installed globally.

**Windows (PowerShell)**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If activation is blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

**Linux (bash)**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Running

```bash
# The real target: build and serve the WASM bundle at http://localhost:8000
python -m pygbag main.py

# Build only, without the test server
python -m pygbag --build main.py

# Native dev run — fast iteration, never used to judge timing
python -m piu
```

`pygbag.ini` controls what goes into the bundle. It exists because pygbag's built-in
ignore list covers `/venv` but not `/.venv`; without it the entire virtualenv gets
packaged.

## Default keyboard layout

The five keys `W A S D X` form a plus, while the panels form an X, so the mapping is a
single consistent 45° counter-clockwise rotation rather than five arbitrary choices:

```
   Panels                 Keys              Mapping
  UL     UR                 W          W -> Up-Left      A -> Down-Left
      C        <-- 45° -- A  S  D      D -> Up-Right     X -> Down-Right
  DL     DR                 X          S -> Center
```

The numpad already sits in an X and ships as a second preset:
`7 = UL, 9 = UR, 5 = C, 1 = DL, 3 = DR`. In Double mode the left pad uses `WASDX` and
the right pad uses the numpad.

## Tests

```bash
python -m pytest
```

The engine core — [piu/core](piu/core), [piu/formats](piu/formats),
[piu/gameplay](piu/gameplay) — never imports pygame, so chart parsing, beat/time math,
judgment, and scoring are all testable with no display and no audio device. A test
enforces this, and it doubles as a WASM portability guard: that code is pure standard
library and runs unchanged under Emscripten.

## Deployment

Pushing to `main` runs [the Pages workflow](.github/workflows/deploy-pages.yml): tests,
then a pygbag build, then a check that the bundle contains no virtualenv or test files,
then deploy. The WASM runtime itself is loaded from pygame-web's CDN rather than
bundled, which is why the published artifact is measured in kilobytes.
