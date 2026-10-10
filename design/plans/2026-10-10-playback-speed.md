# Playback Speed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A 50–100% playback-speed slider that slows the original media and the Demucs stems without changing pitch, keeping the stems sample-aligned and the Grid in sync.

**Architecture:** One client-side `playbackSpeed` value drives the master media (`playbackRate` + `preservesPitch`), the elements stem engine (scaled drift correction), and the graph stem engine. Below 100%, the graph engine routes its mix through one vendored SoundTouch AudioWorklet; at 100% the path is exactly today's. All logic lives in `chordflask/templates/home.html` as top-level functions, so the existing Node-based frontend tests can extract and run them.

**Tech Stack:** Flask/Jinja template with inline JS, Web Audio API (AudioWorklet), SoundTouchJS `@soundtouchjs/audio-worklet` 2.1.1 (MPL-2.0), pytest, Node for frontend tests.

**Spec:** `design/specs/2026-10-10-playback-speed-design.md`

## Global Constraints

- Speed range **50–100%, step 5%**; no speed-up, no reset button.
- Pitch never changes; master media uses `preservesPitch = true`.
- Graph engine is kept. Below 100%, all stems go through **one** stretcher after the per-stem gains. At exactly 100%, the path is `source → gain → destination` (unchanged).
- Nothing is written to analysis JSON; no server route or persistence format changes. Persistence is `localStorage` only, key `chordflask.speedByMedia`.
- The vendored processor stays **byte-for-byte unmodified**. sha256 `59635b112697ad403f7aebb46fc5386231d5db06877707afcec19f555b4d68ca` (`soundtouch-processor.js`); its `LICENSE` sha256 is `753801acf995db0807e9dab615775310b1f74696e7776ee246bf9b31714cdaf9`.
- Do not touch `VERSION`, `CNAME` or the snapshot marker. `THIRD_PARTY_NOTICES.md` may be edited (user approved 2026-10-10).
- Ruff line length 110. Tests use plain `assert`, temp dirs only, never the real `~/.chordflask` or media dirs.
- Frontend JS tests follow `tests/test_stem_graph_frontend.py`: extract `    function name(` blocks from the template and run them with `node -e`; they **skip when Node is absent** (CI has no Node). New functions must be top-level `function` declarations (4-space indent). The extractor stops at the next 4-space `function`, `async function` or `// ` line.
- Work on the branch `feature/playback-speed`, created from `main` before Task 1. Never commit to `main` and never push unless the user asks.

## Commit protocol

Each task ends with exactly one commit (user decision 2026-10-10: no single
large commit at the end). The commit step of every task is these four actions:

1. **Simplify:** run the `/simplify` skill on the task's uncommitted changes and
   apply its fixes. It must not change behavior, rename the task's Interfaces
   names, or edit the vendored SoundTouch files.
2. **Verify the commit builds on its own:** run `make check`. Expected: all
   tests pass (Node tests may SKIP only if Node is absent; say so), Ruff is clean,
   `compileall` succeeds and `git diff --check` is clean. Fix and repeat from 1
   if anything fails.
3. **Stage only this task's files:** `git add <the task's Files list>`, then
   `git status --short` shows nothing else staged and no leftover changes from
   this task.
4. **Commit** with the task's message, ending with the line
   `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

A task's code may define stubs that later tasks extend (for example
`speedControlLocked()` returning `false` in Task 3). Every commit must leave the
app working: at the commit, the app starts, plays and shows the Grid exactly as
before, plus whatever the task adds.

## Review Focus

1. **Seek or A–B loop jump while slowed:** the listener must never hear audio buffered from the old position. Pinned in Task 4 (`fresh-stretcher-per-start`).
2. **Corrupt or out-of-range stored speed** (`"abc"`, `0.3`, `1.4`, `0.73`): it must load as 100% or snap to the nearest 5% step inside the range. Pinned in Task 2 (`normalize`).
3. **Slider dragged while paused** (no graph sources running): no error, and the next start uses the new rate. Pinned in Task 4 (`retime-while-paused`).
4. **Stems turned off after being forced to 100% on plain-HTTP LAN:** master playback returns to the remembered speed. Pinned in Task 4 (`unavailable-stretcher`).
5. **Switching songs:** the new song gets its own remembered speed (or 100%), even when its media element is swapped. Pinned in Task 2 (`master-rate`), via `defaultPlaybackRate`.

---

### Task 1: Vendor SoundTouch processor, packaging and notices

Before starting: `git switch -c feature/playback-speed main` (only the spec and this
plan may be untracked). Commit them first, on their own:
`git add design/specs/2026-10-10-playback-speed-design.md design/plans/2026-10-10-playback-speed.md`
with the message `docs(speed): add playback speed spec and plan` (no `/simplify` or
`make check` needed for documents outside `docs/`).

**Files:**
- Create: `chordflask/static/vendor/soundtouch/soundtouch-processor.js` (copied unmodified from the npm tarball `.dist/soundtouch-processor.js`)
- Create: `chordflask/static/vendor/soundtouch/LICENSE` (copied unmodified from the tarball)
- Modify: `pyproject.toml` (`[tool.setuptools.package-data]` `chordflask` list)
- Modify: `flask/build_standalone.sh:104-105` (add `--add-data` for `chordflask/static`)
- Modify: `THIRD_PARTY_NOTICES.md` (new `## SoundTouchJS` section before `## Python Dependencies`)
- Test: `tests/test_soundtouch_vendor.py`

**Interfaces:**
- Produces: the URL `/static/vendor/soundtouch/soundtouch-processor.js`, which registers the AudioWorklet processor name `'soundtouch-processor'` with AudioParams `pitch`, `pitchSemitones` and `playbackRate`.

- [ ] **Step 1: Fetch and verify the tarball** into a fresh scratch directory (not the repo):
  `curl -s -o aw.tgz https://registry.npmjs.org/@soundtouchjs/audio-worklet/-/audio-worklet-2.1.1.tgz`, then check that `echo "sha512-$(openssl dgst -sha512 -binary aw.tgz | base64 -w0)"` prints `sha512-itxSW62gbtDKoFo6eEr4PXzVz3oF+wCVREupFi5JiUR31tWWwCizr+2XezYD1SnkrSDfdmZvvviTtoyejYeD0Q==`. Extract it and copy the two files into place.

- [ ] **Step 2: Write the failing tests** in `tests/test_soundtouch_vendor.py`:

```python
VENDOR = REPO_ROOT / "chordflask/static/vendor/soundtouch"
PROCESSOR_SHA256 = "59635b112697ad403f7aebb46fc5386231d5db06877707afcec19f555b4d68ca"
LICENSE_SHA256 = "753801acf995db0807e9dab615775310b1f74696e7776ee246bf9b31714cdaf9"

def test_vendored_processor_is_unmodified():
    assert sha256(VENDOR / "soundtouch-processor.js") == PROCESSOR_SHA256
    assert sha256(VENDOR / "LICENSE") == LICENSE_SHA256
    assert "registerProcessor(PROCESSOR_NAME" in (VENDOR / "soundtouch-processor.js").read_text()

def test_flask_serves_processor_as_javascript():
    client = FlaskMP4App().app.test_client()
    response = client.get("/static/vendor/soundtouch/soundtouch-processor.js")
    assert response.status_code == 200
    assert "javascript" in response.content_type

def test_processor_is_package_data():
    data = tomllib.loads(PYPROJECT.read_text())["tool"]["setuptools"]["package-data"]["chordflask"]
    assert "static/vendor/soundtouch/soundtouch-processor.js" in data
    assert "static/vendor/soundtouch/LICENSE" in data

def test_standalone_bundles_static_folder():
    text = (REPO_ROOT / "flask/build_standalone.sh").read_text()
    assert '--add-data "${PROJECT_ROOT}/chordflask/static:chordflask/static"' in text

def test_third_party_notices_name_soundtouchjs():
    text = (REPO_ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    for needle in ("## SoundTouchJS", "@soundtouchjs/audio-worklet", "2.1.1", "MPL-2.0",
                   "https://github.com/cutterbl/SoundTouchJS", "https://mozilla.org/MPL/2.0/",
                   "Olli Parviainen", "unmodified"):
        assert needle in text
```

- [ ] **Step 3: Run** `make test TEST_ARGS="-q tests/test_soundtouch_vendor.py"`. Expected: the package-data, build-script and notices tests FAIL (the file tests pass after Step 1).

- [ ] **Step 4: Implement.** Add the two package-data entries and the `--add-data` line after the `assets` line. Write the notices section: package name, version, license, copyright holders (Olli Parviainen, Ryan Berdeen, Jakub Fiala, Steve 'Cutter' Blades), the source URL, the statement "shipped unmodified at `chordflask/static/vendor/soundtouch/`", the MPL text URL, and that it is used only by the browser for slowed stem playback.

- [ ] **Step 5: Run** `make test TEST_ARGS="-q tests/test_soundtouch_vendor.py tests/test_packaging.py tests/test_documentation.py tests/test_ffmpeg_integration.py tests/test_standalone_runtime_gate.py"`. Expected: PASS.

- [ ] **Step 6: Simplify, verify and commit** per the Commit protocol, with the message `chore(speed): vendor SoundTouchJS audio worklet 2.1.1`.

---

### Task 2: Speed state, persistence and master media

**Files:**
- Modify: `chordflask/templates/home.html`. Add to `storageKeys` (~line 2890), put the functions next to `rememberedSemitones` (~line 3688), and hook song load where `loadedMediaIdentity = requestedPath` is set (~line 5318).
- Test: `tests/test_playback_speed_frontend.py` (Node harness modeled on `tests/test_stem_graph_frontend.py`)

**Interfaces:**
- Produces:
  - `PLAYBACK_SPEED_MIN = 0.5`, `PLAYBACK_SPEED_MAX = 1`, `PLAYBACK_SPEED_STEP = 0.05`; `let playbackSpeed = 1`.
  - `storageKeys.speedByMedia = 'chordflask.speedByMedia'`.
  - `normalizePlaybackSpeed(value) -> number`: a non-finite value gives `1`; otherwise clamp to [0.5, 1] and snap to the nearest 0.05, rounded to 2 decimals.
  - `rememberedPlaybackSpeed(mediaIdentity) -> number` and `rememberPlaybackSpeed(mediaIdentity, speed) -> void` (same try/catch shape as transpose).
  - `effectivePlaybackSpeed() -> number`: returns `playbackSpeed` in this task. Task 4 adds the unavailable-stretcher rule.
  - `applyMasterPlaybackSpeed(rate) -> void`: on `videoPlayer` and `audioPlayer`, sets `preservesPitch = true`, `defaultPlaybackRate = rate`, `playbackRate = rate`.
  - `applyPlaybackSpeed() -> void`: computes `effectivePlaybackSpeed()` and calls `applyMasterPlaybackSpeed`. Tasks 3–5 extend it with UI and stem calls.
  - `setPlaybackSpeed(value) -> void`: normalizes, assigns, calls `rememberPlaybackSpeed(loadedMediaIdentity, …)`, then `applyPlaybackSpeed()`.

- [ ] **Step 1: Write the failing Node tests** (parametrized like `test_stem_graph_behaviour`):
  - `normalize`: `normalizePlaybackSpeed('abc') === 1`, `(NaN) === 1`, `(0.3) === 0.5`, `(1.4) === 1`, `(0.73) === 0.75`, `(0.72) === 0.7`, `(0.85) === 0.85`.
  - `persistence` (with a fake `localStorage` object): after `rememberPlaybackSpeed('a.mp3', 0.7)`, `rememberedPlaybackSpeed('a.mp3') === 0.7` and `rememberedPlaybackSpeed('b.mp3') === 1`. Corrupt JSON in the key gives `1`, and a stored `0.2` gives `0.5`.
  - `master-rate`: with fake `videoPlayer`/`audioPlayer` objects, `setPlaybackSpeed(0.7)` sets `playbackRate`, `defaultPlaybackRate` and `preservesPitch === true` on **both** players.

- [ ] **Step 2: Run** `make test TEST_ARGS="-q tests/test_playback_speed_frontend.py"`. Expected: FAIL (functions not found). If Node is absent the tests SKIP. Report that; installing Node is the user's call.

- [ ] **Step 3: Implement** the Produces list. On song load, next to the transpose lookup: `playbackSpeed = rememberedPlaybackSpeed(requestedPath); applyPlaybackSpeed();`. Call `applyPlaybackSpeed()` before the new `src` is assigned, so `defaultPlaybackRate` takes effect.

- [ ] **Step 4: Run** the same command. Expected: PASS.

- [ ] **Step 5: Simplify, verify and commit** per the Commit protocol, with the message `feat(speed): add per-song playback speed for the master media`.

---

### Task 3: Speed chip, slider popover and BPM readout

**Files:**
- Modify: `chordflask/templates/home.html`
  - Markup: inside `<span class="display-tools">`, right after `<span class="transpose-control">…</span>` (~line 2389).
  - CSS: next to `.stem-mixer` (~line 1438), plus each responsive block that hides `display-tools` children (check lines ~1563, ~1729, ~1872, ~2202) so the chip stays visible on tablet and phone.
  - JS: next to `openStemMixer` (~line 4388); BPM at ~line 5996.
- Test: `tests/test_playback_speed_frontend.py`

**Interfaces:**
- Consumes: `setPlaybackSpeed`, `playbackSpeed`, `effectivePlaybackSpeed` (Task 2).
- Produces:
  - Markup ids:
    - `speedChip` (button, text `100%`, `aria-label="Playback speed"`, `onclick="toggleSpeedPopover()"`)
    - `speedPopover` (div, `hidden`, styled with the stem-mixer popover class, generalized rather than duplicated)
    - `speedValue` (span)
    - `speedSlider` (`<input type="range" id="speedSlider" min="50" max="100" step="5" value="100" oninput="onSpeedSliderInput()" aria-label="Playback speed">`)
  - `toggleSpeedPopover()`, `closeSpeedPopover()`; outside click and Escape close it, matching the stem mixer.
  - `onSpeedSliderInput() -> void`: calls `setPlaybackSpeed(Number(speedSlider.value) / 100)`.
  - `updateSpeedUI() -> void`:
    - chip text is `Math.round(effectivePlaybackSpeed() * 100) + '%'`;
    - class `speed-slowed` is on when effective speed < 1;
    - the slider value follows the speed;
    - `speedSlider.disabled` and the chip `title` follow `speedControlLocked()`, which returns `false` in this task (Task 4 fills it in).
  - `formatBpmStatus(bpm, speed) -> string`: `'BPM: --'` when `bpm` is falsy, `` `BPM: ${bpm}` `` when `speed === 1`, otherwise `` `BPM: ${bpm} → ${Math.round(bpm * speed)}` ``.
  - `applyPlaybackSpeed()` now also calls `updateSpeedUI()` and refreshes `bpmStatus` from the last loaded BPM. Store the BPM in a `let currentBpm` at the existing `bpmStatus.innerText` site.

- [ ] **Step 1: Write the failing tests**:
  - Template contract (plain pytest): the template contains `id="speedChip"`, `id="speedPopover"`, and an `id="speedSlider"` element with `min="50"`, `max="100"`, `step="5"`. Assert that no `max="125"` or reset control (`id="speedReset"`) exists.
  - Node `bpm-format`: `formatBpmStatus(129, 1) === 'BPM: 129'`, `formatBpmStatus(129, 0.7) === 'BPM: 129 → 90'`, `formatBpmStatus(null, 0.7) === 'BPM: --'`.
  - Node `chip`: with fake elements, `setPlaybackSpeed(0.75)` gives chip text `75%`, the `speed-slowed` class on, and slider value `'75'`; `setPlaybackSpeed(1)` turns the class off.

- [ ] **Step 2: Run** `make test TEST_ARGS="-q tests/test_playback_speed_frontend.py"`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement** the Produces list.

- [ ] **Step 4: Run** the same command plus `tests/test_grid_frontend.py tests/test_stem_graph_frontend.py`. Expected: PASS.

- [ ] **Step 5: Visual check:** `make run`, then screenshot desktop, tablet (~800 px) and phone (~390 px) widths. The chip is visible and the popover opens and closes in all three. Report to the user if this can't be done here.

- [ ] **Step 6: Simplify, verify and commit** per the Commit protocol, with the message `feat(speed): add speed slider and effective BPM readout`.

---

### Task 4: Graph engine time-stretch

**Files:**
- Modify: `chordflask/templates/home.html`. Stem graph section, ~lines 2945–2972 (state) and 4946–5023 (`stemGraphPosition`, `startStemGraph`, `activateStemGraph`), plus `clearStemGraph` (~line 4430).
- Modify: `tests/test_stem_graph_frontend.py` (extend the fake context; existing tests must still pass unchanged at rate 1)
- Test: `tests/test_playback_speed_frontend.py`

**Interfaces:**
- Consumes: `effectivePlaybackSpeed`, `applyPlaybackSpeed`, `speedControlLocked`, `updateSpeedUI` (Tasks 2–3); the processor name `'soundtouch-processor'` (Task 1).
- Produces:
  - State: `const STEM_STRETCH_PROCESSOR_URL = '/static/vendor/soundtouch/soundtouch-processor.js'`; `let stemStretchAvailable = false; let stemStretchNode = null; let stemMixBus = null; let stemStretchLoad = null; let stemStretchLatencies = {};` (rate → seconds, one page session).
  - `async function loadStemStretch(ctx) -> Promise<boolean>`: loads the module once per context (memoized in `stemStretchLoad`). Returns `false` when `ctx.audioWorklet` is missing or `addModule` rejects. It never throws.
  - `async function measureStemStretchLatency(rate) -> Promise<number|null>`: the spike algorithm. Render 3 s in an `OfflineAudioContext(2, 3*44100, 44100)` containing a 20 ms 1 kHz burst at 1.0 s, with the source and worklet `playbackRate` both set to `rate`. Find the first sample above 20% of the peak and return `first / 44100 − 1.0 / rate` (`null` if none). Cache the result in `stemStretchLatencies[rate]`; on failure, `console.warn` and return `null`.
  - `stemStretchLatency(rate) -> number`: the cached value for `rate`; otherwise the cached value at the nearest rate; otherwise `0`. Never negative.
  - `connectStemGraphOutput(ctx, rate) -> void`: disconnects the per-stem gains and any old stretcher. If `rate < 1 && stemStretchAvailable`, it creates a **fresh** `new AudioWorkletNode(ctx, 'soundtouch-processor', { outputChannelCount: [2] })` with its `playbackRate` param set to `rate`, and connects gains → `stemMixBus` → node → `ctx.destination`. Otherwise it connects gains → `ctx.destination` and sets `stemStretchNode = null`.
  - Anchor shape `{ when, offset, latency, rate }`. `stemGraphPosition()` returns `offset + (ctx.currentTime − when − latency) × rate`.
  - `startStemGraph()`:
    - `rate = effectivePlaybackSpeed()`; call `connectStemGraphOutput(ctx, rate)`;
    - `latency` = base + output latency + (`stemStretchNode ? stemStretchLatency(rate) : 0`);
    - `offset = master.currentTime + (STEM_GRAPH_START_LEAD + latency) × rate`;
    - each source gets `playbackRate.value = rate`.
    - If `rate < 1` and the latency for this rate isn't cached, start `measureStemStretchLatency(rate)` without awaiting it.
  - `retimeStemGraph(rate) -> void`:
    - **No graph anchor:** does nothing.
    - **Crossing 100%** (`(rate < 1) !== (stemGraphAnchor.rate < 1)`): calls `startStemGraph()`.
    - **Otherwise:** at `tc = ctx.currentTime`:
      - compute `q = offset + (tc − when) × oldRate` (the source position being fed now);
      - set the anchor to `{ when: tc, offset: q, latency: same, rate }`;
      - call `setValueAtTime(rate, tc)` on every source `playbackRate` and on the stretcher's `playbackRate` param.
  - `speedControlLocked()`: `stemsActive && stemEngine === 'graph' && !stemStretchAvailable`.
  - `effectivePlaybackSpeed()`: `speedControlLocked() ? 1 : playbackSpeed`.
  - `applyPlaybackSpeed()`: when `stemsActive && stemEngine === 'graph'`, it also calls `retimeStemGraph(effective)`.
  - `activateStemGraph`:
    - `stemStretchAvailable = await loadStemStretch(ctx)` before stems go active;
    - creates `stemMixBus` once per context;
    - calls `applyPlaybackSpeed()` after `stemsActive = true`, so the locked state and the master rate update.
  - `teardownStems()` calls `applyPlaybackSpeed()` at the end, so the master returns to the remembered speed.

- [ ] **Step 1: Write the failing Node tests.** Extend the fake context with `createGain()`, a `destination`, and an `AudioWorkletNode` stub that records `parameters.get('playbackRate')`, `connect` and `disconnect`. Give `FakeParam` a `setValueAtTime(value, time)` that records calls. Tests:
  - `rate-1-unchanged`: with `playbackSpeed = 1`, every gain connects to `destination`, no worklet node is created, and the existing START_ALIGNMENT numbers hold (`offset 42.08`, position 42 → 44).
  - `slowed-start`:
    - setup: `playbackSpeed = 0.5`, `stemStretchAvailable = true`, `stemStretchLatencies[0.5] = 0.1`;
    - every source `playbackRate.value === 0.5`; one worklet is created with `playbackRate` 0.5; gains → mix bus → worklet → destination;
    - `offset ≈ 42 + (0.05 + 0.03 + 0.1) × 0.5`;
    - after `currentTime += 2`, the position is `42 + 1`.
  - `retime-live`: start at 0.7, advance the clock 1 s, then `retimeStemGraph(0.5)`. No new sources are started, every source got `setValueAtTime(0.5, tc)`, the worklet param got the same, and `stemGraphPosition()` is continuous across the change (within 1e-9).
  - `cross-100`: at 0.7, `retimeStemGraph(1)` restarts (4 new sources) and gains are connected to `destination`; `retimeStemGraph(0.7)` restarts again with a fresh worklet.
  - `fresh-stretcher-per-start`: two `startStemGraph()` calls at 0.7 create two distinct worklet nodes, and the first one was disconnected.
  - `retime-while-paused`: with `stemGraphAnchor = null`, `retimeStemGraph(0.6)` throws nothing and starts nothing. The next `startStemGraph()` uses rate 0.6.
  - `unavailable-stretcher`:
    - with `stemStretchAvailable = false`, `stemsActive = true`, `stemEngine = 'graph'`, `playbackSpeed = 0.7`: `effectivePlaybackSpeed() === 1`, `speedControlLocked() === true`, and the master `playbackRate` after `applyPlaybackSpeed()` is 1;
    - with `stemsActive = false` and another `applyPlaybackSpeed()`, the master rate is 0.7.

- [ ] **Step 2: Run** `make test TEST_ARGS="-q tests/test_playback_speed_frontend.py tests/test_stem_graph_frontend.py"`. Expected: the new tests FAIL and the existing ones PASS.

- [ ] **Step 3: Implement** the Produces list. Keep the drift check and resync threshold unchanged. They work on the rate-aware `stemGraphPosition()`.

- [ ] **Step 4: Run** the same command. Expected: PASS.

- [ ] **Step 5: Simplify, verify and commit** per the Commit protocol, with the message `feat(speed): time-stretch graph-engine stems with SoundTouch`.

---

### Task 5: Elements engine rate

**Files:**
- Modify: `chordflask/templates/home.html`. These lines set or compare `playbackRate` against `1`: ~4825 (`wireStemLifecycle`), ~5071 (`activateStemElements`), ~5168 (`stemMasterSeeked`), ~5211–5232 (`stemDriftCheck`).
- Test: `tests/test_playback_speed_frontend.py`

**Interfaces:**
- Consumes: `effectivePlaybackSpeed`, `applyPlaybackSpeed` (Tasks 2/4).
- Produces:
  - `stemElementRate(delta = 0) -> number` = `effectivePlaybackSpeed() × (1 + delta)`. Every former `= 1` / `!== 1` in those lines uses `stemElementRate()`.
  - The soft-drift branch sets `stemElementRate(delta)`.
  - `applyStemElementRates() -> void` sets `stemElementRate()` on every stem element; `applyPlaybackSpeed()` calls it when `stemEngine === 'elements'`.

- [ ] **Step 1: Write the failing Node test** `elements-drift`. Extract `stemDriftCheck`, `stemElementRate` and `effectivePlaybackSpeed`, with fake elements, `stemEngine = 'elements'` and `playbackSpeed = 0.5`:
  - drift 0.01 s → the rate is exactly `0.5`;
  - drift 0.08 s → the rate is `0.5 × (1 + min(0.03, 0.08 × 0.25)) = 0.51`;
  - drift 0.5 s → the rate is `0.5` and `currentTime` is set to the master's.

- [ ] **Step 2: Run** `make test TEST_ARGS="-q tests/test_playback_speed_frontend.py"`. Expected: FAIL.

- [ ] **Step 3: Implement** the Produces list.

- [ ] **Step 4: Run** the same command plus `tests/test_stem_graph_frontend.py`. Expected: PASS.

- [ ] **Step 5: Simplify, verify and commit** per the Commit protocol, with the message `feat(speed): apply playback speed to element-engine stems`.

---

### Task 6: Grid timing at reduced speed

**Files:**
- Modify: `chordflask/templates/home.html`. `syncPlaybackPosition` (~line 6109), plus any other spot found by the audit.
- Test: `tests/test_playback_speed_frontend.py`

**Interfaces:**
- Consumes: `effectivePlaybackSpeed` (Task 4).
- Produces: `positionSyncDisplayLead() -> number` (media seconds). It returns `0` when `video.paused || isLooping`; otherwise `Math.min(pollingLeadSeconds + estimatedRoundTripSeconds, 0.25) × effectivePlaybackSpeed()`. `syncPlaybackPosition` uses it in place of the inline `displayLead` expression.

- [ ] **Step 1: Write the failing Node test** `display-lead`. With `pollingLeadSeconds = 0.1` and `estimatedRoundTripSeconds = 0.05`:
  - the lead is `0.15` at speed 1 and `0.075` at speed 0.5;
  - `0` when paused; `0` when `isLooping`;
  - the cap holds: `estimatedRoundTripSeconds = 1` at 0.5 gives `0.125`.

- [ ] **Step 2: Run** `make test TEST_ARGS="-q tests/test_playback_speed_frontend.py"`. Expected: FAIL.

- [ ] **Step 3: Implement** the Produces item.

- [ ] **Step 4: Audit:** `grep -n "performance.now\|setTimeout\|setInterval" chordflask/templates/home.html`. For each hit on a playback, loop, lyrics or journal timing path, check whether it converts wall-clock time into media time. Scale every such conversion by `effectivePlaybackSpeed()` and give each fix its own Node test in this file. List the hits and the verdict for each in the task report, including the ones that need no change.

- [ ] **Step 5: Run** `make test TEST_ARGS="-q tests/test_playback_speed_frontend.py tests/test_grid_frontend.py"`. Expected: PASS.

- [ ] **Step 6: Simplify, verify and commit** per the Commit protocol, with the message `fix(speed): scale grid display lead by playback speed`.

---

### Task 7: Documentation, full check and manual verification

**Files:**
- Modify: `README.md` (`## What you can do`: one bullet on practice speed)
- Modify: `docs/DEMUCS.md` (stem playback section: slowed stems use the bundled SoundTouch worklet, which needs `localhost` or HTTPS; on plain-HTTP LAN, speed is locked to 100% while stems are on)
- Test: `tests/test_documentation.py` (add one test)

- [ ] **Step 1: Write the failing test** `test_docs_describe_playback_speed`:
  - `README.md` mentions `speed` and `50%`;
  - `docs/DEMUCS.md` mentions `SoundTouch`, `HTTPS` and `100%`.

- [ ] **Step 2: Run** `make test TEST_ARGS="-q tests/test_documentation.py"`. Expected: FAIL. Then update both docs and confirm it passes.

- [ ] **Step 3: Run** `make check`. Expected: test + lint + compileall + `git diff --check` all pass. Report the skipped Node tests explicitly if Node is absent.

- [ ] **Step 4: Manual browser checklist** with the user, on `make run` at `http://localhost:5000`:
  - **Matrix:** 100/85/70/50% × {master only, graph stems, elements stems (media > 15 min)}. Pitch unchanged, stems aligned, Grid on the beat. Use a song without known beat-tracking errors, *not* The Girl From Ipanema.
  - **Interactions:**
    - live drag while playing;
    - seek while slowed;
    - A–B loop while slowed;
    - switch songs: each keeps its own speed;
    - crossing 100%: one brief gap only.
  - **Plain-HTTP LAN tablet** (`chordflask --listen 0.0.0.0`):
    - slider disabled while graph stems are on, with a tooltip;
    - speed works with stems off;
    - the remembered speed comes back after stems are turned off.
  - **Layouts:** desktop, tablet and phone show the chip and popover.

- [ ] **Step 5: Simplify, verify and commit** per the Commit protocol, with the message `docs(speed): document playback speed`.
