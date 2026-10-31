from text import words


def test_lowercase_without_accents_or_punctuation():
    assert words("¡Apágate, Jarvis!") == ["apagate", "jarvis"]


def test_numbers_and_underscores_are_not_words():
    assert words("las 8_y 42") == ["las", "y"]


def test_any_alphabet():
    assert words("Привет мир") == ["привет", "мир"]
