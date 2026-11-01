"""On its own: notices (politely), calendar notices and the morning summary."""

import asyncio
import time

import pytest

import hub
import kernel
import settings

kernel.load_all()
notices = kernel.load("notices")
calendar = kernel.load("calendar-notices")
morning = kernel.load("morning")
google = kernel.load("google")
Event = google.Event


def at(hour, minute=0):
    now = time.localtime()
    return time.mktime((now.tm_year, now.tm_mon, now.tm_mday, hour, minute, 0, 0, 0, -1))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(settings, "active", {})
    monkeypatch.setattr(hub, "sessions", {})
    monkeypatch.setattr(hub, "active", None)
    calendar._told.clear()


# --- Notices ---

@pytest.mark.parametrize("hours, hour, quiet", [
    ("23:00-08:00", 23, True), ("23:00-08:00", 3, True), ("23:00-08:00", 8, False), ("23:00-08:00", 12, False),
    ("14:00-16:00", 15, True), ("14:00-16:00", 17, False), ("", 3, False),
])
def test_quiet_hours(hours, hour, quiet):
    settings.active["quiet_hours"] = hours
    assert notices.quiet(at(hour, 30)) is quiet


class Ear:
    wake, awake, speaking = True, False, False

    def deaf(self):
        return False


class Brain:
    def __init__(self):
        self.ear, self.said, self.beeps = Ear(), [], 0

    def say(self, text):
        self.said.append(text)

    def _beep(self, kind):
        self.beeps += 1


class Session:
    class pc:
        connectionState = "connected"

    def __init__(self, id):
        self.id, self.device, self.brain = id, id, Brain()


def two():
    found = [Session("a"), Session("b")]
    for session in found:
        hub.add(session)
    return found


def test_a_notice_on_every_device_with_a_tone_first(monkeypatch):
    monkeypatch.setattr(notices, "quiet", lambda now=None: False)
    a, b = two()
    assert asyncio.run(notices.tell("Dentro de 10 minutos: dentista."))
    assert a.brain.said == b.brain.said == ["Dentro de 10 minutos: dentista."] and a.brain.beeps == 1


def test_or_on_the_last_one_you_talked_to(monkeypatch):
    monkeypatch.setattr(notices, "quiet", lambda now=None: False)
    settings.active["notices_where"] = "last"
    a, b = two()
    hub.active = "a"
    asyncio.run(notices.tell("Hola"))
    assert a.brain.said == ["Hola"] and b.brain.said == []


def test_not_at_night(monkeypatch):
    monkeypatch.setattr(notices, "quiet", lambda now=None: True)
    a, _ = two()
    assert not asyncio.run(notices.tell("Hola")) and a.brain.said == []


def test_it_waits_while_someone_talks_to_it(monkeypatch):
    monkeypatch.setattr(notices, "quiet", lambda now=None: False)
    a, b = two()
    a.brain.ear.awake = True  # in a conversation

    async def run():
        task = asyncio.ensure_future(notices.tell("Hola", wait=5))
        await asyncio.sleep(0.3)
        assert b.brain.said == []  # not yet
        a.brain.ear.awake = False  # it fell asleep
        return await task

    assert asyncio.run(run()) and b.brain.said == ["Hola"]


# --- Calendar notices ---

def test_each_event_is_told_once_ahead_of_time(es):
    now = at(9, 50)
    events = [Event("1", "Dentista", at(10), False), Event("2", "Comida", at(14), False),
              Event("3", "Día de Todos los Santos", None, True)]
    found = calendar.due(events, now)
    assert [e.title for e in found] == ["Dentista"]
    assert calendar.sentence(found[0], now) == "Dentro de 10 minutos: Dentista."
    assert calendar.due(events, now + 30) == []  # told already
    moved = [Event("1", "Dentista", at(10, 5), False)]
    assert calendar.due(moved, at(9, 56))  # moved: told again


def test_calendar_now(en):
    event = Event("1", "", at(10), False)
    assert calendar.sentence(event, at(10)) == "Now: an event with no title."


def test_settings_minutes(es):
    settings.active["calendar_notice_minutes"] = 30
    assert calendar.due([Event("1", "Tren", at(10), False)], at(9, 31))


# --- The morning summary ---

def test_greetings(es):
    assert morning.is_greeting("Buenos días.") and morning.is_greeting("Buenos días, Eva")
    assert not morning.is_greeting("Buenos días, ¿qué tiempo hace hoy en Málaga?")


def test_the_summary(es, monkeypatch):
    class Google:
        def today_left(self, now):
            return [Event("h", "Día de Todos los Santos", None, True)], [
                Event("1", "dentista", at(10), False), Event("2", "llamar a Ana", at(17), False)]

        def unread(self, query):
            return 3, False

    monkeypatch.setattr(kernel, "module", lambda name: Google() if name == "google" else None)
    said = morning.summary(at(8))
    assert said.startswith("Buenos días. Hoy es ")
    assert ": Día de Todos los Santos." in said
    assert "En la agenda tienes 2 cosas: a las 10 en punto de la mañana, dentista y a las 5 en punto de la tarde, llamar a Ana." in said
    assert said.endswith("Tienes 3 emails sin leer.")


def test_without_google_it_still_greets(es, monkeypatch):
    monkeypatch.setattr(kernel, "module", lambda name: None)
    assert morning.summary(at(8)).startswith("Buenos días. Hoy es ")


def test_after_the_first_morning_alarm(monkeypatch):
    given = []
    monkeypatch.setattr(morning, "give", given.append)
    monkeypatch.setattr(morning, "_given", "")
    morning_at, real = at(7, 30), time.localtime
    monkeypatch.setattr(time, "localtime", lambda t=None: real(morning_at if t is None else t))
    morning._after_the_alarm("assistant", {"kind": "timer"})
    morning._after_the_alarm("assistant", {"kind": "alarm"})
    morning._after_the_alarm("assistant", {"kind": "alarm"})  # snoozed and stopped again: once a day
    assert given == ["assistant"]
