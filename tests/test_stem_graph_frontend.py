"""Exercise the shared-clock stem engine with a fake AudioContext."""
from pathlib import Path
import shutil
import subprocess

import pytest


TEMPLATE = Path(__file__).resolve().parents[1] / 'chordflask/templates/home.html'

GRAPH_FUNCTIONS = [
    'stemGraphSupported',
    'stemGraphGain',
    'applyStemGain',
    'stemGraphPosition',
    'stopStemGraphSources',
    'startStemGraph',
    'stemMasterPlaying',
    'stemMasterInterrupted',
    'stemGraphDriftCheck',
]


def _function_source(template, name):
    start = template.index(f'    function {name}(')
    end = min(
        index for index in (
            template.find('\n    function ', start + 1),
            template.find('\n    async function ', start + 1),
            template.find('\n    // ', start + 1),
        ) if index >= 0
    )
    return template[start:end]


def graph_script(body):
    """Build a runtime-neutral script: no Node APIs, failures throw."""
    template = TEMPLATE.read_text()
    functions = '\n'.join(_function_source(template, name) for name in GRAPH_FUNCTIONS)
    return r'''
function assert(condition, message) { if (!condition) throw new Error(message || 'assertion failed'); }
function near(actual, expected, message) {
  assert(Math.abs(actual - expected) < 1e-9, (message || '') + ': ' + actual + ' != ' + expected);
}
const STEM_NAMES = ['vocals', 'drums', 'bass', 'other'];
const STEM_GRAPH_MAX_SECONDS = 15 * 60;
const STEM_GRAPH_START_LEAD = 0.05;
const STEM_GRAPH_RESYNC_DRIFT = 0.060;
const STEM_GRAPH_GAIN_TIME_CONSTANT = 0.01;
let stemsActive = true;
let stemEngine = 'graph';
let stemBuffers = {};
let stemGains = {};
let stemSources = {};
let stemGraphAnchor = null;
let stemStates = { vocals: true, drums: true, bass: true, other: true };
let stemVolumes = { vocals: 1.0, drums: 0.5, bass: 1.0, other: 1.0 };
const started = [];
class FakeSource {
  connect(node) { this.output = node; }
  disconnect() { this.output = null; }
  start(when, offset) { this.when = when; this.offset = offset; started.push(this); }
  stop() { this.stopped = true; }
}
class FakeParam {
  constructor() { this.value = 1; this.targets = []; }
  setTargetAtTime(value, time, constant) { this.targets.push([value, time, constant]); }
}
const stemAudioContext = {
  currentTime: 10, baseLatency: 0.01, outputLatency: 0.02, state: 'running',
  createBufferSource() { return new FakeSource(); },
  resume() { return Promise.resolve(); },
};
const window = { AudioContext: function () {} };
let video = { currentTime: 42, paused: false, ended: false, seeking: false, readyState: 4, duration: 300 };
for (const name of STEM_NAMES) {
  stemBuffers[name] = { duration: 300 };
  stemGains[name] = { name, gain: new FakeParam() };
}
''' + functions + '\n' + body


def run_graph_script(body):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is unavailable')
    result = subprocess.run(
        [node, '-e', graph_script(body)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr


START_ALIGNMENT = r'''
startStemGraph();
assert(started.length === 4, 'every stem starts');
const first = started[0];
for (const source of started) {
  near(source.when, first.when, 'shared start time');
  near(source.offset, first.offset, 'shared offset');
}
near(first.when, 10.05, 'start lead');
// Offset compensates the lead and the audio output latency.
near(first.offset, 42 + 0.05 + 0.03, 'latency-compensated offset');
STEM_NAMES.forEach((name, index) => assert(started[index].output === stemGains[name], name + ' gain'));
// The audible graph position matches the master's position.
near(stemGraphPosition(), 42, 'position at start');
stemAudioContext.currentTime = 12;
video.currentTime = 44;
near(stemGraphPosition(), 44, 'position after two seconds');
'''

RESYNC = r'''
startStemGraph();
// Small master jitter never restarts the sources.
video.currentTime = 42.03;
stemGraphDriftCheck(video);
assert(started.length === 4, 'no restart under the resync threshold');
// A drift of the whole graph restarts all stems together at one offset.
video.currentTime = 42.2;
stemGraphDriftCheck(video);
assert(started.length === 8, 'all stems restart');
assert(started.slice(0, 4).every(source => source.stopped), 'old sources stopped');
const restarted = started.slice(4);
assert(restarted.every(source => source.offset === restarted[0].offset), 'restart stays aligned');
'''

INTERRUPTIONS = r'''
startStemGraph();
stemMasterInterrupted({ target: { other: true } });
assert(stemGraphAnchor !== null, 'events from the inactive player are ignored');
stemMasterInterrupted({ target: video });
assert(stemGraphAnchor === null && Object.keys(stemSources).length === 0, 'seek or stall silences');
assert(started.every(source => source.stopped), 'sources stopped');
stemMasterPlaying({ target: video });
assert(started.length === 8 && stemGraphAnchor !== null, 'playing restarts');
stemMasterPlaying({ target: video });
assert(started.length === 8, 'playing does not restart a running graph');
'''

GAINS_AND_LIMITS = r'''
assert(stemGraphGain('drums') === 0.5, 'volume');
stemStates.drums = false;
assert(stemGraphGain('drums') === 0, 'muted stems use exact zero gain');
applyStemGain('drums');
const target = stemGains.drums.gain.targets[0];
assert(target[0] === 0 && target[1] === 10 && target[2] === 0.01, 'smooth gain change');
assert(stemGraphSupported({ duration: 300 }), 'short media uses the graph');
assert(!stemGraphSupported({ duration: 15 * 60 + 1 }), 'long media keeps separate players');
assert(!stemGraphSupported({ duration: NaN }), 'unknown duration keeps separate players');
video.currentTime = 299.99;
startStemGraph();
assert(started.length === 0 && stemGraphAnchor === null, 'nothing starts past the end');
'''


@pytest.mark.parametrize('body', [START_ALIGNMENT, RESYNC, INTERRUPTIONS, GAINS_AND_LIMITS],
                         ids=['start-alignment', 'resync', 'interruptions', 'gains-and-limits'])
def test_stem_graph_behaviour(body):
    run_graph_script(body)


def graph_source(template, name):
    start = template.index(f'    async function {name}(')
    return template[start:template.index('\n    function ', start)]


LOADING_UI = r"""
const STEM_NAMES = ['vocals', 'drums', 'bass', 'other'];
let stemEngine = null;
let stemsActive = false;
let stemsAvailable = true;
let stemMixerStem = null;
let stemStates = { vocals: true, drums: true, bass: true, other: true };
const calls = [];
function element() {
  const classes = new Set();
  return {
    attributes: {},
    classList: { toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
                 contains(name) { return classes.has(name); } },
    setAttribute(name, value) { this.attributes[name] = value; },
  };
}
const stemsButton = element();
const stemTogglesRow = element();
function stemChipEl() { return element(); }
function stemChip() { return element(); }
function stemLevelEl() { return element(); }
const STEM_LABELS = { vocals: {}, drums: {}, bass: {}, other: {} };
function stemPercent() { return 100; }
function updateStemMixer() {}
function updatePrepareStemsButton() {}
function teardownStems() { calls.push('teardown'); stemEngine = null; stemsActive = false; }
function activateStems() { calls.push('activate'); stemEngine = 'graph'; updateStemsUI(); }
""" + '\n'.join(
    _function_source(TEMPLATE.read_text(), name)
    for name in ('stemsLoading', 'updateStemsUI', 'toggleStems')
) + r"""
function assert(condition, message) { if (!condition) throw new Error(message || 'assertion failed'); }
toggleStems();
assert(calls.join() === 'activate', 'first click activates');
assert(stemsButton.classList.contains('stem-loading'), 'loading is shown');
assert(stemsButton.attributes['aria-busy'] === 'true', 'loading is announced');
assert(!stemsButton.classList.contains('stem-on'), 'not shown as on yet');
toggleStems();
assert(calls.join() === 'activate,teardown', 'second click cancels instead of reloading');
assert(!stemsButton.classList.contains('stem-loading'), 'loading cleared after cancel');
assert(stemsButton.attributes['aria-busy'] === 'false', 'not busy after cancel');
"""


def test_stem_loading_click_cancels():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is unavailable')
    result = subprocess.run([node, '-e', LOADING_UI], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_stem_graph_wiring_contract():
    template = TEMPLATE.read_text()
    activate = _function_source(template, 'activateStems')
    graph = template[template.index('    async function activateStemGraph('):
                     template.index('    function activateStems(')]
    toggle = _function_source(template, 'toggleStem')
    teardown = _function_source(template, 'teardownStems')

    assert 'if (stemGraphSupported(master))' in activate
    assert 'activateStemElements(token);' in activate
    # The context resumes before the first await so the STEMS click unlocks audio.
    assert graph.index('ctx.resume()') < graph.index('await')
    # A failed decode falls back to separate players.
    assert 'activateStemElements(token);' in graph.split('catch (error)', 1)[1]
    assert 'applyStemGain(name);' in toggle
    assert 'clearStemGraph();' in teardown
    # Stem downloads stop when stems are torn down or the song changes.
    assert 'fetchStemBuffer(ctx, name, controller.signal)' in graph
    assert 'stemFetchController.abort();' in _function_source(template, 'clearStemGraph')
    # Decoders that resolve nothing fall back instead of playing silence.
    fetch_buffer = graph_source(template, 'fetchStemBuffer')
    assert 'fetch(stemStreamUrl(name), { signal })' in fetch_buffer
    assert "if (!buffer) throw new Error('Stem decoding is unavailable');" in fetch_buffer
    # Choosing an engine shows the loading state at once.
    assert activate.rstrip().endswith('updateStemsUI();\n    }')
    for event, handler in [('playing', 'stemMasterPlaying'), ('waiting', 'stemMasterInterrupted'),
                           ('seeking', 'stemMasterInterrupted')]:
        assert f"player.addEventListener('{event}', {handler});" in template
