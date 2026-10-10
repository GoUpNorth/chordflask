"""Exercise the playback-speed controls with fake media elements and storage."""
from pathlib import Path
import pytest

from test_stem_graph_frontend import _function_source, run_node


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
function speedControlLocked() { return false; }
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
