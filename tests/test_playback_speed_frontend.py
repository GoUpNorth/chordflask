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


def run_speed_script(body, functions=SPEED_FUNCTIONS, prelude=PRELUDE):
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
