import json

import pytest

import settings
from plugins.skill_language import command as language_command


@pytest.fixture
def file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "PATH", path)
    return path


def test_no_file_no_settings(file):
    assert settings.load() == {}


def test_broken_file_is_ignored(file):
    file.write_text("{oops")
    assert settings.load() == {}


def test_save_keeps_the_rest(file):
    file.write_text(json.dumps({"llm": "apple", "voice": {"es": "Mónica"}}))
    settings.save(language="en")
    assert settings.load() == {"llm": "apple", "voice": {"es": "Mónica"}, "language": "en"}
    assert "Mónica" in file.read_text()  # readable, not \\u00f3


def test_voice_for_each_language():
    assert settings.voice_for("Eddy", "es") == "Eddy"
    assert settings.voice_for({"es": "Mónica", "en": "Daniel"}, "en") == "Daniel"
    assert settings.voice_for({"es": "Mónica"}, "en") is None  # the language's default
    assert settings.voice_for(None, "en") is None


def test_restart_drops_the_language_option():
    argv = ["server/main.py", "--lang", "es", "--llm", "apple", "--lang=en"]
    assert settings.without_option(argv, "--lang") == ["server/main.py", "--llm", "apple"]


@pytest.mark.parametrize("text, code", [
    ("Speak Spanish", "es"),
    ("Switch to English.", "en"),
    ("Talk to me in Spanish", "es"),
    ("Háblame en inglés", "en"),
    ("Jarvis, habla en español", "es"),
    ("Cambia a inglés", "en"),
    ("Speak English", "en"),  # as Parakeet may write it while in Spanish
])
def test_language_command(lang, text, code):
    assert language_command(text) == code


@pytest.mark.parametrize("text", [
    "¿Quién habla inglés en Suiza?",
    "Pasa el correo a inglés",
    "How do you say hello in Spanish?",
    "Speak louder",
    "Spanish",
])
def test_not_a_language_command(lang, text):
    assert language_command(text) is None


@pytest.fixture
def active(monkeypatch):
    monkeypatch.setattr(settings, "active", {})
    return settings.active


def test_instructions_with_name_and_your_own(en, active):
    from llm import instructions

    assert instructions().startswith("You are Jarvis,")
    active.update(name="Friday", instructions="I invoice with Holded.")
    text = instructions()
    assert text.startswith("You are Friday,") and text.endswith("I invoice with Holded.")


def test_another_name_in_a_language_command(en, active):
    active["name"] = "Friday"
    assert language_command("Friday, speak Spanish") == "es"


def test_transcripts_stay_out_of_the_log_unless_asked(active):
    assert settings.private("my bank password is 1234") == "[24 characters]"
    active["log_transcripts"] = True
    assert settings.private("hello") == "hello"


def test_the_readme_lists_every_option():
    import options
    from conftest import ROOT

    readme = (ROOT / "README.md").read_text()
    table = readme[readme.index("<!-- options:"):readme.index("<!-- /options -->")]
    assert options.markdown() in table, "run: python server/options.py markdown"


def test_options_check():
    import options

    assert options.check({"skin": "eyes", "memory": "auto", "detail": "concise"}) == []
    problems = options.check({"skin": "smiley", "memory": "sometimes", "detail": "verbose"})
    assert len(problems) == 3 and any("smiley" in p for p in problems)


def test_the_command_line_has_every_option():
    import options

    args = options.parser().parse_args(["--lang", "es", "--no-fillers", "--volume", "70", "--voice", "Mónica",
                                        "--detail-levels", '{"x": "Be short."}'])
    assert (args.language, args.fillers, args.volume, args.voice) == ("es", False, 70, "Mónica")
    assert args.detail_levels == {"x": "Be short."}
