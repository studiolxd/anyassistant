import pytest

from plugins.stt_parakeet import wrong_language


@pytest.mark.parametrize("text", ["That's true.", "Koda is a very good idea", "tři"])
def test_spanish_drifting_into_another_language(es, text):
    assert wrong_language(text)


@pytest.mark.parametrize("text", ["¿Qué hora es?", "Mañana a las ocho", "No", ""])
def test_spanish_is_fine(es, text):
    assert not wrong_language(text)


def test_english_with_foreign_letters(en):
    assert wrong_language("Cześć")
    assert not wrong_language("What time is it?")
