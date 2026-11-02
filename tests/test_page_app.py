"""The page in an app (?app: the iPhone, iPad, Mac and Android apps draw every theme but Eyes in
a web view with it): it tells the app it is ready, draws what the app gives it (the server's
messages, the app's own problems) and gives the app its taps. Run in node (tests/page_app.js)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


@pytest.fixture(scope="module")
def run():
    done = subprocess.run(["node", str(HERE / "page_app.js"), "orb"], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_it_loads_its_theme_and_says_it_is_ready(run):
    assert run["fetched"] == ["/config?theme=orb"]
    assert run["sent"] == [{"type": "ready"}]  # no WebRTC, no microphone: the app has them
    assert run["screenShown"] and run["appClass"]


def test_it_draws_what_the_app_gives_it(run):
    assert run["thinking"] == {"state": "thinking", "status": "Pensando…"}
    assert run["captions"] == [["¿Qué hora es?", ""], ["Son las diez.", "assistant"]]
    assert run["asleep"] == "Di «Oye, Eva»"


def test_the_apps_problem_until_it_clears(run):
    assert run["problem"] == {"state": "error", "status": "Buscando el servidor…"}
    assert run["cleared"] == {"state": "thinking", "status": "Pensando…"}  # back as it was


def test_the_camera_window_is_where_the_app_shows_its_own(run):
    shown, hidden = run["cameraMessages"]
    assert shown["type"] == "camera" and shown["on"] and shown["width"] > 0 and shown["height"] > 0
    assert hidden == {"type": "camera", "on": False}


def test_a_tap_and_holding_the_face_go_to_the_app(run):
    assert run["tap"] == [{"type": "tap"}]
    assert run["held"] == [{"type": "settings"}]  # held: its settings, not also a tap
