"""Contracts for the vendored SoundTouchJS AudioWorklet processor."""

import hashlib
from fnmatch import fnmatch
import tomllib
from pathlib import Path

from chordflask.app import FlaskMP4App


REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
VENDOR = REPO_ROOT / "chordflask/static/vendor/soundtouch"
PROCESSOR_SHA256 = "59635b112697ad403f7aebb46fc5386231d5db06877707afcec19f555b4d68ca"
LICENSE_SHA256 = "753801acf995db0807e9dab615775310b1f74696e7776ee246bf9b31714cdaf9"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_vendored_processor_is_unmodified():
    assert sha256(VENDOR / "soundtouch-processor.js") == PROCESSOR_SHA256
    assert sha256(VENDOR / "LICENSE") == LICENSE_SHA256


def test_flask_serves_processor_as_javascript():
    client = FlaskMP4App().app.test_client()
    response = client.get("/static/vendor/soundtouch/soundtouch-processor.js")
    assert response.status_code == 200
    assert "javascript" in response.content_type


def test_processor_is_package_data():
    patterns = tomllib.loads(PYPROJECT.read_text())["tool"]["setuptools"]["package-data"]["chordflask"]
    package = REPO_ROOT / "chordflask"
    for name in ("soundtouch-processor.js", "LICENSE"):
        relative = (VENDOR / name).relative_to(package).as_posix()
        assert any(fnmatch(relative, pattern) for pattern in patterns), relative


def test_standalone_bundles_static_folder():
    text = (REPO_ROOT / "flask/build_standalone.sh").read_text()
    assert '--add-data "${PROJECT_ROOT}/chordflask/static:chordflask/static"' in text


def test_third_party_notices_name_soundtouchjs():
    text = (REPO_ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    for needle in ("## SoundTouchJS", "@soundtouchjs/audio-worklet", "2.1.1", "MPL-2.0",
                   "https://github.com/cutterbl/SoundTouchJS", "https://mozilla.org/MPL/2.0/",
                   "Olli Parviainen", "unmodified"):
        assert needle in text
