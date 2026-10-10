# Playback speed — design spec

Status: approved design (2026-10-10). Not user documentation; user-facing text
lands in `README.md` and `docs/DEMUCS.md` during implementation.

## Problem

Students learning a song need to play along slowly before playing at the real
tempo. ChordFlask plays the original media and, optionally, the four Demucs
stems at a fixed 100% speed. The user wants a speed control that slows the
original **and** the stems without changing pitch, while the Grid, Lyrics and
A–B loop stay synchronized.

## Requirements

1. Speed is set as a **percentage from 50% to 100% in 5% steps** (no speed-up,
   no reset button; decision 2026-10-10).
2. **Pitch never changes** at any speed.
3. Speed applies to the original media and to stems, on both stem engines.
4. Stems stay **sample-aligned with each other** at every speed. The graph
   engine is kept; reverting to the elements engine for slowed playback is not
   acceptable (decision 2026-10-10).
5. The control is a **slider**, shaped like the existing stem volume mixer, and
   is available in **every layout** (desktop, tablet, phone).
6. The Grid, Lyrics and A–B loop stay synchronized with the audio at every speed.
7. At 100% the behavior is exactly today's: same audio path, same timing.
8. Speed is a client-side playback preference. Nothing is written to analysis
   JSON, and no server route or persistence format changes.
9. No fallback is required for plain-HTTP LAN access, where AudioWorklet is
   unavailable (decision 2026-10-10); the core must still work there.

## Spike findings (throwaway, 2026-10-10)

A throwaway branch inserted the SoundTouch worklet into the graph engine and was
tested by the user on *The Girl From Ipanema* with stems:

- Stems stayed sample-aligned at 50/70/85%; 0 resyncs; maximum master-vs-graph
  drift 46–52 ms (resync threshold 60 ms).
- Sound quality was judged good for practice.
- Stretcher underruns (~50, cumulative) came from the worklet refilling after
  each restart and were not audible.
- A Grid lag seen during testing was traced to the song's analysis
  (`qm_barbeattracker` locks onto ~85–100 BPM between 59 s and 92 s), not to the
  speed change. It is tracked as a separate bug and is out of scope.
- Found a real rate bug: `syncPlaybackPosition()` adds a wall-clock display
  lead (≤ 0.25 s) to media time. At 50% the Grid runs up to ~0.12 s early.

## Library

**SoundTouchJS `@soundtouchjs/audio-worklet` 2.1.1**, MPL-2.0 (the project
moved from LGPL). It is a JavaScript port of SoundTouch (WSOLA time-stretch,
used by Audacity, VLC and many practice apps). Only the self-contained
processor file `.dist/soundtouch-processor.js` (~72 KB, no imports) is used.
The main-thread `SoundTouchNode` wrapper is not needed: the page creates a plain
`AudioWorkletNode(ctx, 'soundtouch-processor')` and sets its `playbackRate`
AudioParam.

- Vendored **unmodified** at `chordflask/static/vendor/soundtouch/` with its
  `LICENSE`, served by Flask's existing static folder (no new route).
- Provenance: npm tarball
  `https://registry.npmjs.org/@soundtouchjs/audio-worklet/-/audio-worklet-2.1.1.tgz`,
  integrity
  `sha512-itxSW62gbtDKoFo6eEr4PXzVz3oF+wCVREupFi5JiUR31tWWwCizr+2XezYD1SnkrSDfdmZvvviTtoyejYeD0Q==`.
- `THIRD_PARTY_NOTICES.md` gains a SoundTouchJS section: version, license,
  copyright holders (Olli Parviainen, Ryan Berdeen, Jakub Fiala, Steve 'Cutter'
  Blades), upstream source URL, the statement that the file is unmodified, and
  where the MPL-2.0 text can be obtained (user approved, 2026-10-10).
- Packaging: `pyproject.toml` package-data adds the static vendor files;
  `flask/build_standalone.sh` adds `--add-data` for `chordflask/static`.

Rejected alternatives: Signalsmith Stretch (MIT, better transients, less
adoption; user chose SoundTouch), Rubber Band (GPL), server-side pre-rendered
stems (seconds per speed change, disk cost), elements engine for slowed playback
(5–30 ms inter-stem drift made stems unusable).

## Design

### 1. Controls

- A **Speed chip** showing the current value (`100%`), placed in the song bar
  next to the transpose control and visible in every layout. The exact position
  in each layout is settled during implementation with screenshots.
- Tapping the chip opens a **popover with a range slider** (`min=50 max=100
  step=5`) and the current value. It reuses the stem mixer's popover styling and
  open/close behavior (generalized where needed, not duplicated).
- Changes apply **live while dragging** (`input` event).
- The chip is visibly highlighted whenever speed is below 100%.
- The BPM readout shows the effective tempo when slowed, e.g. `BPM: 129 → 90`
  (`Math.round(bpm * speed)`); at 100% it is unchanged.
- **Persistence:** speed is remembered per song in `localStorage`, using the
  same mechanism as transpose (`rememberedSemitones` / `transposeByMedia`).
  Default 100%. A newly loaded song gets its remembered speed, or 100%.

### 2. Speed state

One client-side value `playbackSpeed` (0.5–1.0) is the single source of truth.
`setPlaybackSpeed(value)` clamps and snaps it, stores it, and applies it to the
master media, the active stem engine and the UI. The master media remains the
timeline authority.

### 3. Master media

`videoPlayer` and `audioPlayer` get `preservesPitch = true`, and both
`defaultPlaybackRate` and `playbackRate` are set to `playbackSpeed`.
`defaultPlaybackRate` makes the rate survive source changes. This works in every
context, including plain-HTTP LAN.

### 4. Graph engine (≤ 15 min media)

Audio path:

- **At 100%:** `source → per-stem gain → destination`, exactly as today.
- **Below 100%:** `source → per-stem gain → mix bus → SoundTouch worklet →
  destination`. All stems pass through **one** stretcher after mixing, so they
  stay sample-aligned and the CPU cost is one stretcher. The per-stem
  mute/volume mixer is unchanged.

Timing model:

- The graph anchor gains a rate: `position(t) = offset + (t − when − latency) ×
  rate`, where `latency` = output latency + measured stretcher latency (0 when
  bypassed). `startStemGraph()` sets `source.playbackRate = rate`, the worklet's
  `playbackRate` AudioParam to the same value, and starts at
  `offset = master.currentTime + (START_LEAD + latency) × rate`.
- **Speed change below 100% (live drag):** no restart. At one audio-clock
  instant `tc`, compute the source position under the old anchor, set the new
  anchor `{when: tc, offset: that position, rate: new}`, and schedule
  `source.playbackRate` and the worklet `playbackRate` with
  `setValueAtTime(new, tc)`. The few milliseconds of audio already buffered in
  the stretcher at the old rate cause a transient error under ~20 ms. The
  existing drift check resyncs if needed.
- **Crossing the 100% boundary** (bypass ↔ worklet) rebuilds the path and
  restarts the graph once. A brief gap is acceptable.
- Each restart while slowed uses a **fresh worklet node**, so audio buffered
  from the previous position is never heard after a seek.
- **Stretcher latency** is measured offline per speed, the first time that
  speed is used, by rendering a short tone burst through the processor in an
  `OfflineAudioContext` (spike method), then cached for the page session. Until
  measured, the nearest cached value (or 0) is used and the drift check covers
  the gap.
- **Worklet loading:** `audioWorklet.addModule()` runs once per AudioContext
  when stems activate. A missing `audioWorklet` (non-secure context) or a load
  failure marks the stretcher unavailable; it never fails stem activation.

### 5. Elements engine (> 15 min media)

Every place that resets a stem element to `playbackRate = 1` uses
`playbackSpeed` instead. Drift correction sets
`playbackRate = playbackSpeed × (1 + delta)`. `preservesPitch` is already set.
Seeks and sync logic otherwise stay unchanged.

### 6. Stretcher unavailable (plain-HTTP LAN)

When stems are active on the graph engine and the stretcher is unavailable,
the effective speed is 100% for both master and stems. The slider is disabled
with a tooltip explaining that slowed stem playback needs `localhost` or HTTPS.
The remembered speed is kept and applies again when stems are turned off. With
stems off, or on the elements engine, speed works everywhere.

### 7. Grid, Lyrics, A–B loop

- `syncPlaybackPosition()` scales the display lead to media time:
  `displayLead × playbackSpeed`. This fixes the early-Grid bug from the spike.
- Implementation audits the playback paths for other wall-clock-vs-media-time
  assumptions (`performance.now()`, `setTimeout`/`setInterval` predictions
  around position, loop or lyrics timing) and scales them the same way.
- Lyrics follow the Grid and add no clock (existing invariant). The A–B loop
  works on media time and needs no change beyond that audit.

## Error handling

- Worklet module fails to load, or the node throws on creation: the stretcher is
  marked unavailable and §6 applies. Stem playback at 100% is unaffected.
- Offline latency measurement fails: latency 0 is used, logged with
  `console.warn`. The drift check keeps the graph within the resync threshold.
- Invalid stored speed values (non-numeric, out of range) fall back to 100%.

## Out of scope

Speeds above 100%; a reset button; HTTPS or a stretcher fallback for LAN;
changing the 15-minute graph-engine limit; the Ipanema beat-tracking bug;
count-in or metronome; per-stem time-stretching; saving speed to analysis JSON.

## Testing

Automated (pytest, following existing contract-test patterns):

- The template contains the speed chip and slider with `min="50"`, `max="100"`,
  `step="5"`.
- The Flask test client serves
  `/static/vendor/soundtouch/soundtouch-processor.js` with a JavaScript content
  type.
- Packaging: package-data includes the vendor files (`tests/test_packaging.py`),
  and the standalone build script bundles `chordflask/static`.
- The vendored processor matches the recorded upstream file (checksum), and its
  `LICENSE` is present.
- `THIRD_PARTY_NOTICES.md` contains the SoundTouchJS entry.
- Documentation tests still pass after the `README.md` / `docs/DEMUCS.md`
  updates.

Manual browser checklist (there is no JS runtime in CI):

- Speeds 100/85/70/50% × {master only, graph-engine stems, elements-engine
  stems (> 15 min media)}: pitch unchanged, stems aligned, Grid on the beat.
- Live slider drag while playing; seek; A–B loop; song change keeps the
  per-song speed; crossing 100%.
- Plain-HTTP LAN on a tablet: slider disabled while graph stems are on; speed
  works with stems off.
- Desktop, tablet and phone layouts show the chip and popover.
- `spikeStats`-style checks are not shipped. Drift can be checked in DevTools
  with temporary logging only.
