"""What Jarvis understands by voice: system commands, «yes», going to sleep."""

import pytest

from brain.assistant import is_yes, split, system_command
from brain.ear import is_sleep_command

CASES = {
    "en": {
        "sleep": ["Go to sleep", "Sleep, Jarvis.", "Goodnight"],
        "not_sleep": ["How long should I sleep before a flight to Tokyo?"],
        "reload": ["Reload the tools", "Reload."],
        "restart": ["Restart", "Reboot, please"],
        "yes": ["Yes", "Sure, do it", "Okay."],
        "not_yes": ["No, wait", "Yes no", "Yes I think we should probably send the email to everyone today"],
    },
    "es": {
        "sleep": ["Apágate", "Apparaté.", "Duérmete, Jarvis"],
        "not_sleep": ["¿Cómo se apaga el horno de la cocina nueva?"],
        "reload": ["Recarga las herramientas", "Recargar"],
        "restart": ["Reiníciate", "Reinicia el servidor"],
        "yes": ["Sí", "Vale, hazlo", "Adelante."],
        "not_yes": ["No, espera", "Sí, pero mejor no", "Sí creo que deberíamos mandar el correo a todos hoy mismo"],
    },
}


@pytest.fixture
def cases(lang):
    return CASES[lang.code]


def test_sleep(cases):
    assert all(is_sleep_command(t) for t in cases["sleep"])
    assert not any(is_sleep_command(t) for t in cases["not_sleep"])


def test_system_commands(cases):
    assert all(system_command(t) == "reload" for t in cases["reload"])
    assert all(system_command(t) == "restart" for t in cases["restart"])
    assert system_command(cases["not_sleep"][0]) is None
    assert system_command("") is None


def test_yes(cases):
    assert all(is_yes(t) for t in cases["yes"])
    assert not any(is_yes(t) for t in cases["not_yes"])


def test_split_into_sentences():
    assert split("Hi. How a") == (["Hi."], "How a")
    assert split("One! Two? Three…\nFour") == (["One!", "Two?", "Three…"], "Four")
    assert split("No end yet") == ([], "No end yet")
    assert split("Version 2.5 is out") == ([], "Version 2.5 is out")
