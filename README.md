# piu

A 5-panel, upward-scrolling rhythm game in the style of Andamiro's *Pump It Up*.
Runs on Windows and Linux on a pygame-ce / SDL2 stack.

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
or step charts are included in this repository, and none will be accepted into it.

Songs are supplied at runtime:

- `songs/demo/` holds originally-authored charts over permissively-licensed audio, so
  the game is playable immediately after install.
- `songs/manifest.toml` names community charts that `tools/fetch_songs.py` downloads
  from their creators' own distribution links into a gitignored cache. Third-party
  audio and charts never enter this repository's history.

## Setup

Requires Python 3.12+. Everything runs inside a project-local virtual environment;
nothing is installed globally.

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
sudo apt install libsdl2-2.0-0 libportaudio2 python3-venv   # or your distro's equivalent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Running

```bash
python -m piu                    # boot to title
python -m piu --song <folder>    # jump straight into a chart
python -m piu --calibrate        # audio/input offset calibration
```

## Default keyboard layout

The five keys `W A S D X` form a plus, while the panels form an X, so the mapping is a
single consistent 45° counter-clockwise rotation:

```
   Panels                 Keys              Mapping
  UL     UR                 W          W -> Up-Left      A -> Down-Left
      C        <-- 45° -- A  S  D      D -> Up-Right     X -> Down-Right
  DL     DR                 X          S -> Center
```

The numpad maps onto the X shape directly and ships as a second preset:
`7 = UL, 9 = UR, 5 = C, 1 = DL, 3 = DR`. In Double mode the left pad uses `WASDX` and
the right pad uses the numpad.

## Tests

```bash
python -m pytest
```

The engine core (`piu/core`, `piu/formats`, `piu/gameplay`) never imports pygame, so
chart parsing, beat/time math, judgment, and scoring are all testable headlessly — no
display and no audio device required. A test enforces this.
