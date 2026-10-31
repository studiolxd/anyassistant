"""What Jarvis understands by voice: system commands, «yes», going to sleep."""

import pytest

import kernel
from brain.assistant import split

is_yes = kernel.load("confirmation").is_yes
from plugins.skill_restart import command as system_command
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
        "not_sleep": ["¿Cómo se apaga el horno de la cocina nueva?", "Apaga la cámara", "Apaga la luz"],
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


def test_stop(lang):
    from brain.ear import is_stop_command

    stop, other = {"en": ("Stop!", "Stop the music in the kitchen"), "es": ("¡Para!", "Para qué sirve esto")}[lang.code]
    assert is_stop_command(stop)
    assert not is_stop_command(other)


@pytest.mark.parametrize("text, expected", [
    ("Turn on the camera", "on"), ("Show the camera", "on"), ("Turn off the camera.", "off"),
    ("Hide the camera", "off"), ("What camera do you have?", None), ("Turn on the lights", None),
])
def test_camera_english(en, text, expected):
    from plugins.skill_camera import command as camera_command

    assert camera_command(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Activa la cámara", "on"), ("Jarvis, enciende la cámara", "on"), ("Muéstrame la cámara", "on"),
    ("Apaga la cámara", "off"), ("Quita la cámara.", "off"), ("¿Qué cámara tienes?", None),
])
def test_camera_spanish(es, text, expected):
    from plugins.skill_camera import command as camera_command

    assert camera_command(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Use Claude", "claude"), ("Switch to Hermes.", "hermes"), ("Jarvis, use the Apple model", "apple"),
    ("Use cloud", "claude"), ("Use the oven timer", None), ("What does Claude think?", None),
])
def test_llm_english(en, text, expected):
    from plugins.skill_choose_llm import command as llm_command

    assert llm_command(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Usa Claude", "claude"), ("Cambia a Hermes", "hermes"), ("Pásate al modelo de Apple", "apple"),
    ("Cambia la cara", None), ("¿Qué opina Claude?", None),
])
def test_llm_spanish(es, text, expected):
    from plugins.skill_choose_llm import command as llm_command

    assert llm_command(text) == expected
