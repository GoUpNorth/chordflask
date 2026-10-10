"""Exercise the playback-speed controls with fake media elements and storage."""
from pathlib import Path
import pytest

from test_stem_graph_frontend import _function_source, run_graph_script, run_node


TEMPLATE = Path(__file__).resolve().parents[1] / 'chordflask/templates/home.html'

PRELUDE = r'''
function assert(condition, message) { if (!condition) throw new Error(message || 'assertion failed'); }
function near(actual, expected, message) {
  assert(Math.abs(actual - expected) < 1e-9, (message || '') + ': ' + actual + ' != ' + expected);
}
const PLAYBACK_SPEED_MIN = 0.5;
const PLAYBACK_SPEED_MAX = 1;
const PLAYBACK_SPEED_STEP = 0.05;
let playbackSpeed = 1;
let loadedMediaIdentity = 'a.mp3';
let stemsActive = false;
let stemEngine = null;
let stemStretchAvailable = false;
const storageKeys = { speedByMedia: 'chordflask.speedByMedia' };
const localStorage = {
  items: {},
  getItem(key) { return Object.prototype.hasOwnProperty.call(this.items, key) ? this.items[key] : null; },
  setItem(key, value) { this.items[key] = String(value); },
};
function fakePlayer() { return { playbackRate: 1, defaultPlaybackRate: 1, preservesPitch: false }; }
const videoPlayer = fakePlayer();
const audioPlayer = fakePlayer();
'''

SPEED_FUNCTIONS = [
    'normalizePlaybackSpeed',
    'readStoredObject',
    'rememberForMedia',
    'rememberedPlaybackSpeed',
    'rememberPlaybackSpeed',
    'effectivePlaybackSpeed',
    'speedControlLocked',
    'graphStemsActive',
    'applyMasterPlaybackSpeed',
    'applyPlaybackSpeed',
    'setPlaybackSpeed',
]


def run_speed_script(body, functions=SPEED_FUNCTIONS, prelude=PRELUDE + 'function updateSpeedUI() {}\n'):
    template = TEMPLATE.read_text()
    source = '\n'.join(_function_source(template, name) for name in functions)
    run_node(prelude + source + '\n' + body)


NORMALIZE = r'''
assert(normalizePlaybackSpeed('abc') === 1, 'text');
assert(normalizePlaybackSpeed(NaN) === 1, 'NaN');
assert(normalizePlaybackSpeed(0.3) === 0.5, 'below range');
assert(normalizePlaybackSpeed(1.4) === 1, 'above range');
assert(normalizePlaybackSpeed(0.73) === 0.75, 'snaps up');
assert(normalizePlaybackSpeed(0.72) === 0.7, 'snaps down');
assert(normalizePlaybackSpeed(0.85) === 0.85, 'on step');
'''

PERSISTENCE = r'''
rememberPlaybackSpeed('a.mp3', 0.7);
assert(rememberedPlaybackSpeed('a.mp3') === 0.7, 'remembered');
assert(rememberedPlaybackSpeed('b.mp3') === 1, 'default');
rememberPlaybackSpeed('a.mp3', 1);
assert(!('a.mp3' in JSON.parse(localStorage.items[storageKeys.speedByMedia])), 'full speed is not stored');
localStorage.items[storageKeys.speedByMedia] = '{not json';
assert(rememberedPlaybackSpeed('a.mp3') === 1, 'corrupt json');
localStorage.items[storageKeys.speedByMedia] = JSON.stringify({ 'a.mp3': 0.2 });
assert(rememberedPlaybackSpeed('a.mp3') === 0.5, 'clamped stored value');
'''

MASTER_RATE = r'''
setPlaybackSpeed(0.7);
for (const player of [videoPlayer, audioPlayer]) {
  near(player.playbackRate, 0.7, 'rate');
  near(player.defaultPlaybackRate, 0.7, 'default rate survives source changes');
  assert(player.preservesPitch === true, 'pitch preserved');
}
assert(rememberedPlaybackSpeed('a.mp3') === 0.7, 'stored for the loaded song');
'''


@pytest.mark.parametrize('body', [NORMALIZE, PERSISTENCE, MASTER_RATE],
                         ids=['normalize', 'persistence', 'master-rate'])
def test_playback_speed_state(body):
    run_speed_script(body)


def test_speed_controls_are_a_50_to_100_percent_slider_without_reset():
    template = TEMPLATE.read_text()
    assert 'id="speedChip"' in template
    assert 'id="speedPopover"' in template
    at = template.index('id="speedSlider"')
    slider = template[template.rindex('<input', 0, at):template.index('>', at)]
    for attribute in ('type="range"', 'min="50"', 'max="100"', 'step="5"'):
        assert attribute in slider
    assert 'id="speedReset"' not in template


UI_PRELUDE = PRELUDE + r'''
function fakeElement() {
  const classes = new Set();
  return {
    textContent: '', innerText: '', title: '', value: '', disabled: false, hidden: true,
    classList: { toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
                 contains(name) { return classes.has(name); } },
  };
}
const speedChip = fakeElement();
const speedSlider = fakeElement();
const speedPopover = fakeElement();
const bpmStatus = fakeElement();
let currentBpm = 129;
'''

UI_FUNCTIONS = SPEED_FUNCTIONS + ['formatBpmStatus', 'updateSpeedUI', 'onSpeedSliderInput']

BPM_FORMAT = r'''
assert(formatBpmStatus(129, 1) === 'BPM: 129', 'full speed');
assert(formatBpmStatus(129, 0.7) === 'BPM: 129 → 90', 'slowed');
assert(formatBpmStatus(null, 0.7) === 'BPM: --', 'unknown');
'''

CHIP = r'''
setPlaybackSpeed(0.75);
assert(speedChip.textContent === '75%', 'chip text ' + speedChip.textContent);
assert(speedChip.classList.contains('speed-slowed'), 'slowed highlight');
assert(speedSlider.value === '75', 'slider follows');
assert(bpmStatus.innerText === 'BPM: 129 → 97', 'bpm readout ' + bpmStatus.innerText);
speedSlider.value = '100';
onSpeedSliderInput();
assert(playbackSpeed === 1 && speedChip.textContent === '100%', 'slider input sets speed');
assert(!speedChip.classList.contains('speed-slowed'), 'highlight off at full speed');
assert(bpmStatus.innerText === 'BPM: 129', 'bpm at full speed');
'''


@pytest.mark.parametrize('body', [BPM_FORMAT, CHIP], ids=['bpm-format', 'chip'])
def test_speed_ui(body):
    run_speed_script(body, functions=UI_FUNCTIONS, prelude=UI_PRELUDE)


RATE_ONE_UNCHANGED = r'''
stemStretchAvailable = true;
startStemGraph();
assert(worklets.length === 0, 'no stretcher at full speed');
STEM_NAMES.forEach(name => assert(stemGains[name].output === stemAudioContext.destination, name));
assert(started.every(source => source.playbackRate.value === 1), 'sources at full rate');
near(started[0].offset, 42.08, 'unchanged offset');
stemAudioContext.currentTime = 12;
near(stemGraphPosition(), 44, 'unchanged position');
'''

SLOWED_START = r'''
playbackSpeed = 0.5;
stemStretchAvailable = true;
stemStretchLatencies[0.5] = 0.1;
startStemGraph();
assert(worklets.length === 1, 'one stretcher');
const stretch = worklets[0];
assert(stretch.name === 'soundtouch-processor', 'processor name');
assert(stretch.params.playbackRate.value === 0.5, 'stretcher rate');
assert(stretch.output === stemAudioContext.destination, 'stretcher to output');
STEM_NAMES.forEach(name => assert(stemGains[name].output === stretch, name + ' through stretcher'));
assert(started.every(source => source.playbackRate.value === 0.5), 'sources slowed');
near(started[0].offset, 42 + (0.05 + 0.03 + 0.1) * 0.5, 'latency-compensated offset');
stemAudioContext.currentTime = 12;
near(stemGraphPosition(), 43, 'position advances at half speed');
assert(measured.length === 0, 'cached latency is not re-measured');
'''

RETIME_LIVE = r'''
playbackSpeed = 0.7;
stemStretchAvailable = true;
startStemGraph();
const latency = stemGraphAnchor.latency;
stemAudioContext.currentTime = 11;
const fedAt = stemGraphAnchor.offset + (11 - stemGraphAnchor.when) * 0.7;
retimeStemGraph(0.5);
assert(started.length === 4 && worklets.length === 1, 'no restart below full speed');
started.forEach(source => {
  const last = source.playbackRate.scheduled.at(-1);
  assert(last[0] === 0.5 && last[1] === 11, 'source rate scheduled now');
});
assert(worklets[0].params.playbackRate.scheduled.at(-1)[0] === 0.5, 'stretcher rate scheduled');
// Once audio already in flight has played, the position follows the new rate exactly.
stemAudioContext.currentTime = 11 + latency + 2;
near(stemGraphPosition(), fedAt + 2 * 0.5, 'position after retime');
assert(measured.includes(0.5), 'new rate latency measured');
'''

CROSS_100 = r'''
playbackSpeed = 0.7;
stemStretchAvailable = true;
startStemGraph();
playbackSpeed = 1;
retimeStemGraph(1);
assert(started.length === 8, 'crossing to full speed restarts');
assert(worklets[0].disconnected, 'stretcher removed');
STEM_NAMES.forEach(name => assert(stemGains[name].output === stemAudioContext.destination, name));
playbackSpeed = 0.7;
retimeStemGraph(0.7);
assert(started.length === 12 && worklets.length === 2, 'crossing below full speed restarts');
'''

FRESH_STRETCHER = r'''
playbackSpeed = 0.7;
stemStretchAvailable = true;
startStemGraph();
startStemGraph();
assert(worklets.length === 2 && worklets[0] !== worklets[1], 'fresh stretcher per start');
assert(worklets[0].disconnected, 'old stretcher disconnected');
'''

RETIME_PAUSED = r'''
retimeStemGraph(0.6);
assert(started.length === 0, 'nothing starts without an anchor');
playbackSpeed = 0.6;
stemStretchAvailable = true;
startStemGraph();
assert(started.every(source => source.playbackRate.value === 0.6), 'next start uses the new rate');
'''

UNAVAILABLE = r'''
const videoPlayer = { playbackRate: 1 };
const audioPlayer = { playbackRate: 1 };
function updateSpeedUI() {}
playbackSpeed = 0.7;
stemStretchAvailable = false;
assert(effectivePlaybackSpeed() === 1 && speedControlLocked(), 'graph stems lock full speed');
applyPlaybackSpeed();
assert(videoPlayer.playbackRate === 1, 'master follows the locked speed');
stemsActive = false;
applyPlaybackSpeed();
assert(videoPlayer.playbackRate === 0.7, 'remembered speed returns without stems');
'''


@pytest.mark.parametrize('body', [
    RATE_ONE_UNCHANGED, SLOWED_START, RETIME_LIVE, CROSS_100, FRESH_STRETCHER, RETIME_PAUSED,
], ids=['rate-1-unchanged', 'slowed-start', 'retime-live', 'cross-100', 'fresh-stretcher-per-start',
        'retime-while-paused'])
def test_graph_time_stretch(body):
    run_graph_script(body)


def test_unavailable_stretcher_locks_full_speed():
    template = TEMPLATE.read_text()
    extra = '\n'.join(
        _function_source(template, name) for name in ('applyMasterPlaybackSpeed', 'applyPlaybackSpeed')
    )
    run_graph_script(extra + UNAVAILABLE)


STRETCH_LOAD = r'''
const STEM_STRETCH_PROCESSOR_URL = '/static/vendor/soundtouch/soundtouch-processor.js';
let stemStretchLoad = null;
const fail = error => { console.error(error); process.exit(1); };
loadStemStretch({}).then(ok => {
  assert(ok === false, 'missing audioWorklet');
  stemStretchLoad = null;
  return loadStemStretch({ audioWorklet: { addModule: () => Promise.reject(new Error('blocked')) } });
}).then(ok => {
  assert(ok === false, 'module load failure');
  stemStretchLoad = null;
  const urls = [];
  const ctx = { audioWorklet: { addModule: url => { urls.push(url); return Promise.resolve(); } } };
  return Promise.all([loadStemStretch(ctx), loadStemStretch(ctx)]).then(results => {
    assert(results.every(Boolean), 'loaded');
    assert(urls.length === 1 && urls[0] === STEM_STRETCH_PROCESSOR_URL, 'loaded once');
  });
}).catch(fail);
'''


def test_stretch_module_load_never_throws():
    run_speed_script(STRETCH_LOAD, functions=['loadStemStretch'])
