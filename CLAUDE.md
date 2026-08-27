# piu — project guide

A 5-panel, upward-scrolling rhythm game in the style of Andamiro's *Pump It Up*,
compiled to WebAssembly with pygbag and hosted on GitHub Pages.

**Live:** https://xtpotato.github.io/piu/ · **Repo:** `XTPotato/piu` (public)
**Full plan:** `C:\Users\xiren\.claude\plans\plan-a-pump-it-tranquil-bunny.md`

---

## Orientation

| | |
|---|---|
| Target | **The browser is the only shipped artifact.** Desktop is a dev convenience. |
| Stack | pygbag 0.9.3 → CPython 3.12 WASM + pygame-ce. One runtime dependency. |
| Deploy | Push to `main`. CI tests → builds → verifies → deploys. No manual step. |
| Tests | 242, all headless (`SDL_VIDEODRIVER=dummy`). Run them before every commit. |
| Env | `.venv` in the project root, built from `C:\Users\xiren\miniconda3` (3.12.8). |

```
.venv\Scripts\python.exe -m pytest                                    # tests
.venv\Scripts\python.exe -m pygbag --template tools/piu.tmpl \
    --ume_block 0 --build main.py                                     # build
.venv\Scripts\python.exe -m pygbag --template tools/piu.tmpl main.py  # + serve :8000
.venv\Scripts\python.exe -m piu                                       # native dev run
```

---

## Hard rules

These are enforced by tests. Breaking one usually fails **only in the browser**,
often long after boot, with an error that points nowhere near the cause.

1. **`piu/core`, `piu/formats`, `piu/gameplay` must never import pygame.**
   Enforced by `tests/test_core_is_headless.py`, which walks every submodule in a
   subprocess. It keeps the engine testable with no display and doubles as a WASM
   portability guard.

2. **Never touch a pygame attribute at module import time.**
   Under pygbag, `pygame` is not fully populated when our modules import.
   `pygame.K_a` at module scope raises `AttributeError` and kills the game before
   its first frame. Resolve lazily — see `key_codes()` in `piu/screens/boot.py`.

3. **Every runtime dependency must be imported at top level in `main.py`.**
   pygbag decides what to install by statically parsing *that file only*
   (`aio.pep0723.check_list` → `parse_code`). An import nested in `piu/app.py` is
   invisible to it, the package is never installed, and the name resolves to an
   empty stub. Enforced by `tests/test_entrypoint.py`.

4. **Every import must exist in pygbag's trimmed stdlib.**
   `statistics` is absent. So are others. Checked against
   `tests/fixtures/pygbag_stdlib.txt` by `tests/test_pygbag_stdlib.py`, which
   inspects imports at *any* nesting depth. Regenerate with
   `python tools/probe_stdlib.py`.

5. **The game loop is async and yields every frame.**
   `await asyncio.sleep(0)` once per frame or the browser tab hangs. `App.run`
   and every `Screen` method are coroutines.

6. **All async JS work stays in JavaScript; Python polls.**
   Awaiting a JS promise from pygbag Python is the least dependable part of the
   interop. `tools/web_audio.js` does the promise work and exposes a status
   string plus numbers. Never `await` across the bridge.

7. **No Andamiro content, ever.** No official sprites, logos, fonts, songs, or
   step charts in the repo or on the deployed site. This is public.

---

## Roadmap

| | Milestone | Status |
|---|---|---|
| **W0** | Retarget to WASM, deploy pipeline | **Done** |
| **W1** | Web Audio clock + timing gate | **Gate passed**, one reading outstanding |
| W2 | Vertical slice: judge, combo, lifebar, holds, results | Next |
| W3 | Arcade presentation within the WASM budget | |
| W4 | Song select; bundled + fetched content | |
| W5 | Double/half-double, speed mods, rebinding, gamepad | |
| W6 | Persistence (localStorage), release polish | |

### W1 status in detail

Six human tapping runs, all clearing the gate:

- **Spread 18.1–27.7ms** against a 42ms Perfect window. This is the gate's real
  criterion — a constant bias is removed by calibration, spread is not.
- **Bias drifted −100ms → −40ms** while spread stayed flat. A moving centre with
  a stable spread is the player adapting, not the machine changing.
- Chrome reports `outputLatency` as **0.0ms**; only `baseLatency` (10ms) is
  available, so the latency correction works from an incomplete number. Exactly
  what the plan predicted. Calibration is the real fix, not this value.

**Outstanding:** a `clock quality:` line now logs on entering the timing screen,
measuring `AudioContext.currentTime`'s step size — the machine's own floor,
isolated from human jitter. Not yet read. If it comes back "excellent"
(~2.7ms = one render quantum at 48kHz), the pipeline is effectively free and W2
can begin.

---

## Architecture

```
main.py                  pygbag entry. Thin. Top-level `import pygame` is LOad-BEARING.
piu/
  runtime.py             IS_WEB, window(), log(), report_exception().
                         The ONLY place that knows about the browser.
  app.py                 Window, async loop, screen stack, gesture tracking.
  core/       timing.py  Beat<->time: BPM changes, stops, delays, warps.
              clock.py   SongClock ABC, ManualClock (tests), WebAudioClock.
  formats/    chart.py   Canonical Note/Chart/Song model. Everything compiles to this.
              ucs.py  stepmania.py  native.py  __init__.py (registry + library scan)
  gameplay/   offsets.py Input matching, statistics, the gate's verdict.
  input/      layouts.py WASDX/numpad as pure data. web_input.py  JS-stamped keys.
  render/     panels.py  Panel colours; pad X-layout vs on-screen lane row.
  screens/    boot.py    Gesture gate -> panel test. timing_check.py  The W1 rig.
tools/                   Desktop-only. Excluded from the bundle by pygbag.ini.
  boot_diagnostics.js    fetch/XHR wrappers, on-page log panel.
  web_audio.js           Web Audio bridge + input timestamping.
  make_template.py       Inlines the JS into tools/piu.tmpl. Regenerate after editing JS.
  probe_stdlib.py        Captures pygbag's real stdlib into the test fixture.
```

**Editing the JS requires regenerating the template:**
`python tools/make_template.py`, then rebuild. `tools/piu.tmpl` is committed so
builds don't depend on the CDN.

---

## Coding style

Observed and consistent across the codebase. Match it.

- **`.format()`, not f-strings, in `piu/`.** Zero f-strings in the shipped
  package, 51 `.format()` calls. Keeps long messages readable when built by
  implicit concatenation across lines, which is the dominant pattern here.
  `tools/` uses f-strings freely — it is desktop-only.
- **`from __future__ import annotations`** at the top of every module.
- **Type hints everywhere**, including return types.
- **`@dataclass(frozen=True, slots=True)`** for value objects; `slots=True` for
  mutable ones. 13 in use.
- **Module docstrings are mandatory** and explain *why the module exists*, not
  what it contains. Several carry a "Why X rather than Y" section — keep that.
- **Comments explain reasoning, not mechanics.** Never `# increment counter`.
  Do write `# Sorted, so everything further right is worse still.`
- **`#:` doc-comments on module constants** that need justification.
- **Constants are named and placed near what uses them**, not scattered.
- Prefer explicit failure over silent degradation. `runtime.window()` raises on
  desktop rather than returning `None`.
- Diagnostics must never break what they diagnose — wrap in `try/except` and
  carry on.

### Tests

- **`pytest`, grouped into `class Test*` blocks** by behaviour, not by method.
- **Test names are sentences**: `test_a_swap_tears_down_before_setting_up`.
- **Comments in tests explain why the case matters**, especially for regression
  guards. A test that reproduces a production failure should say so.
- **Assert the reason, not just the value.** Failure messages should tell the
  next reader what to do.
- Where a guard exists to catch a specific past bug, include a **precondition
  assertion** proving the bug would otherwise pass. See
  `test_ambiguous_run_fails_the_gate_despite_looking_perfect`.
- Browser-only code is tested through its pure parts (`ManualClock`,
  `offsets`, key-name mapping). Never fake the browser.

### Commits

Long-form prose, not bullet summaries. State what was found, what was ruled
out, and *why* — including approaches that failed and the reason they failed.
Several commits here record dead ends deliberately so they are not retried.
End with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## Decisions already made — do not relitigate

- **Web-only.** No PyInstaller, no desktop release, no `sounddevice`. Running
  natively is for iteration speed only, and **no timing decision is ever made
  outside the browser.**
- **`sounddevice`/`miniaudio`/`numpy`/`platformdirs` were deliberately removed.**
  CFFI/C extensions have no Emscripten build. Web Audio is a better clock anyway:
  same hardware source as the output, monotonic, with a latency figure to subtract.
- **WASDX is a 45° counter-clockwise rotation** of the key plus onto the panel X
  (`W`→Up-Left, `D`→Up-Right, `S`→Centre, `A`→Down-Left, `X`→Down-Right). Numpad
  is the second preset and the right pad in Double.
- **Half-double is the middle six of ten panels** (indices 2–7). One shared
  constant, `HALF_DOUBLE_OFFSET`.
- **The click track is synthesized, not loaded.** Clicks on exact sample indices
  make the timing reference arithmetic, and the rig needs no audio asset.
- **Input is stamped at the DOM keydown in JS**, not polled per frame — frame
  polling costs ~5ms of standard deviation at 60Hz.
- **The gate judges spread, not mean.** Calibration removes bias; nothing removes
  spread. Calibration is suggested from the **median** so outliers cannot drag it.
- **Diagnostics classify by origin.** `FAIL` means the game is broken; injected
  third-party requests log as `OTHER`. A log that cries wolf is worse than none.
- **`browserfs.min.js` 404s and that is fine.** A genuine gap in the pygbag 0.9.3
  CDN under either spelling; the game runs without it. Logged as `WARN`.

---

## Known limitations

- **Browser input latency is the floor**, by choice. The calibration screen is the
  only mitigation and is not yet built (due in W2).
- **`.ucs` semantics are unverified.** No authoritative public spec. Assumptions
  (`Split` = ticks-per-beat, `Beat` cosmetic, `Delay` in ms) are pinned by tests
  in `tests/test_ucs.py`. Validate against real files before trusting it.
- **The WASM runtime loads from `pygame-web.github.io`'s CDN**, not self-hosted.
  That is why the published bundle is ~45KB. It is a third-party dependency.
- **Aliasing near half a beat is unrecoverable.** A 300ms-late tap and a 200ms-early
  one are *identical* patterns. `offsets.is_ambiguous()` refuses such runs rather
  than guessing a direction.
- **`crossOriginIsolated: false`** on GitHub Pages (no custom headers), so no
  `SharedArrayBuffer`. Fine for the single-threaded runtime.
- The user's Chrome has an **ad/tracking extension** (`postUserData` →
  `motramby.com`, `tstats.online`) that delays boot by ~1.9s and produces `OTHER`
  lines in every log. Not ours; ignore it. Edge is the clean test.

---

## Debugging the deployed build

The page carries a diagnostics panel (bottom of screen, **Copy** button). It
wraps `fetch`/`XHR` and logs every request with URL, status, size, timing —
because a bare "Failed to fetch" carries no URL and is unactionable.

Reading a log: ignore anything whose host is neither `xtpotato.github.io` nor
`pygame-web.github.io`. A healthy boot ends with:

```
BOOT  python entry reached: web (pygbag/WASM, CPython 3.12)
OK    display ready at 1280x720
OK    first frame presented
```

`python/piu` failures are reported through `runtime.log` into that same panel,
so a Python traceback reaches whoever is looking at the page.

### The four pygbag traps, in the order they bit

Each cost a deploy cycle. Each now has a guard test. Expect more of this shape —
pygbag's divergences from desktop CPython are only discoverable by running it.

1. `pygame.K_a` at module scope → `AttributeError`. *Guard:* `test_app_loop.py::TestImportSafetyUnderPygbag`
2. pygame never installed, because `main.py` did not import it → `no attribute 'init'`. *Guard:* `test_entrypoint.py`
3. `import statistics` → `ModuleNotFoundError`. *Guard:* `test_pygbag_stdlib.py`
4. `.venv` packaged into the bundle. *Guard:* `pygbag.ini` + the CI extension allowlist.
