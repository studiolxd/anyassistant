"""The plugin «microphone-busy»: another program recording on Windows (the consent store) or Linux
(PipeWire, PulseAudio) pauses the computer's own device."""

import json

import pytest

import hub
import kernel
import settings

kernel.load_all()
busy = kernel.load("microphone-busy")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(settings, "active", {})
    monkeypatch.setattr(hub, "sessions", {})


def test_windows_entries_in_use_are_the_ones_not_stopped():
    entries = [
        ("Microsoft.Teams_8wekyb3d8bbwe", 133000000000000000, 0),  # a packaged app, recording now
        ("Microsoft.WindowsCamera_8wekyb3d8bbwe", 133000000000000000, 133000000001000000),  # done
        (r"NonPackaged\C:#Users#me#AppData#Roaming#Zoom#bin#Zoom.exe", 133000000000000000, 0),
        (r"NonPackaged\C:#Program Files#Google#Chrome#Application#chrome.exe", 0, 0),  # never used
        (r"NonPackaged\C:#Users#me#AppData#Local#Programs#AnyAssistant#AnyAssistant.exe", 133000000000000000, 0),  # ours
    ]
    assert busy.windows_busy(entries) == ["Microsoft.Teams", "Zoom"]


PW_DUMP = json.dumps([
    {"id": 60, "type": "PipeWire:Interface:Node", "info": {"state": "running", "props": {
        "media.class": "Stream/Input/Audio", "application.name": "ZOOM VoiceEngine",
        "application.process.binary": "zoom", "application.process.id": 4242}}},
    {"id": 61, "type": "PipeWire:Interface:Node", "info": {"state": "running", "props": {
        "media.class": "Stream/Input/Audio", "application.name": "Chromium",
        "application.process.binary": "anyassistant"}}},  # our own app's page
    {"id": 62, "type": "PipeWire:Interface:Node", "info": {"state": "suspended", "props": {
        "media.class": "Stream/Input/Audio", "application.name": "Audacity"}}},
    {"id": 63, "type": "PipeWire:Interface:Node", "info": {"state": "running", "props": {
        "media.class": "Stream/Output/Audio", "application.name": "Firefox"}}},
])


def test_pipewire_running_input_streams():
    assert busy.pipewire_busy(PW_DUMP) == ["ZOOM VoiceEngine"]
    assert busy.pipewire_busy("not json") == []


PACTL = """Source Output #12
\tDriver: protocol-native.c
\tCorked: no
\tProperties:
\t\tapplication.name = "Firefox"
\t\tapplication.process.binary = "firefox"
Source Output #13
\tCorked: yes
\tProperties:
\t\tapplication.name = "Audacity"
Source Output #14
\tCorked: no
\tProperties:
\t\tapplication.name = "Chromium"
\t\tapplication.process.binary = "anyassistant"
"""


def test_pulseaudio_uncorked_source_outputs():
    assert busy.pulse_busy(PACTL) == ["Firefox"]
    assert busy.pulse_busy("") == []


def test_it_waits_before_pausing_and_before_resuming():
    watch = busy.Watch()
    assert watch.tick(["Zoom"], 0.0) is None
    assert watch.tick(["Zoom"], 0.5) is None
    assert watch.tick([], 0.7) is None  # a moment's change: forgotten
    assert watch.tick(["Zoom"], 1.0) is None
    assert watch.tick(["Zoom"], 2.1) == "busy" and watch.program == "Zoom"
    assert watch.tick([], 3.0) is None
    assert watch.tick([], 4.5) is None
    assert watch.tick([], 5.1) == "free"


class Ear:
    def __init__(self):
        self.calls = []

    def pause(self, why, app="", source="device"):
        self.calls.append(("pause", why, app, source))

    def resume(self, source=None):
        self.calls.append(("resume", source))


class Session:
    def __init__(self, remote):
        self.remote, self.sent = remote, []
        self.brain = type("Brain", (), {"ear": Ear()})()
        self.id, self.device = remote, remote

    def send(self, message):
        self.sent.append(message)


def test_only_the_computers_own_devices_are_paused():
    own, other = Session("127.0.0.1"), Session("192.168.1.20")
    hub.sessions = {"a": own, "b": other}
    busy.apply("busy", "Zoom")
    assert own.brain.ear.calls == [("pause", "microphone", "Zoom", "server")] and own.sent == [{"type": "pause"}]
    assert not other.brain.ear.calls and not other.sent
    busy.apply("free", "")
    assert own.brain.ear.calls[-1] == ("resume", "server") and own.sent[-1] == {"type": "resume"}


def test_it_only_runs_on_windows_and_linux():
    found = kernel.plugin("microphone-busy")
    assert found.needs["system"] == ["win32", "linux"]
