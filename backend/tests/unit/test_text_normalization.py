"""Spanish text folding, tokenization and the synonym table."""

import pytest

from eventssound.adapters.search.synonyms import CATEGORY_ES, SYNONYM_GROUPS
from eventssound.adapters.search.text import normalize, stem, tokens
from eventssound.domain.catalog import EquipmentCategory


@pytest.mark.parametrize("text", ["parlante", "Parlánte", "PARLANTE", "  parlante\t"])
def test_accent_case_and_whitespace_folding(text: str) -> None:
    assert normalize(text) == "parlante"


def test_enye_folds_consistently() -> None:
    assert normalize("Cañón") == normalize("canon") == "canon"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("par\u200blante", "parlante"),  # zero-width space
        ("par\u200dlan\ufeffte", "parlante"),  # zero-width joiner, BOM
        ("par\u0007lante", "parlante"),  # control character
        ("luces\n\n  de\tescenario", "luces de escenario"),  # whitespace collapsed
        ("\uff2c\uff25\uff24", "led"),  # NFKC: full-width letters
    ],
)
def test_invisible_characters_are_removed_and_whitespace_collapsed(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    ("word", "stemmed"),
    [("parlantes", "parlante"), ("luces", "luz"), ("microfonos", "microfono"), ("gas", "gas"),
     ("luz", "luz"), ("dj", "dj")],
)  # fmt: skip
def test_light_plural_rule(word: str, stemmed: str) -> None:
    assert stem(word) == stemmed


def test_tokens_drop_stopwords_and_punctuation() -> None:
    assert tokens("Quiero un parlante, de 15 pulgadas!") == ("parlante", "15", "pulgada")


def test_stopwords_only_gives_no_tokens() -> None:
    assert tokens("de la en un") == ()


def test_synonyms_map_to_one_canonical_token() -> None:
    assert tokens("bafle") == tokens("altavoz") == tokens("bocina") == tokens("parlante")
    assert tokens("neblina") == tokens("humo")
    assert tokens("iluminacion") == tokens("luces") == tokens("luz")


def test_synonym_groups_are_stored_in_stemmed_form_and_do_not_overlap() -> None:
    seen: dict[str, int] = {}
    for index, group in enumerate(SYNONYM_GROUPS):
        assert len(group) >= 2
        for word in group:
            assert word == normalize(word) and stem(word) == word, word
            assert seen.setdefault(word, index) == index, f"{word} is in two groups"


def test_every_category_has_a_spanish_name() -> None:
    assert set(CATEGORY_ES) == set(EquipmentCategory)
