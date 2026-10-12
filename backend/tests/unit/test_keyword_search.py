"""KeywordSearch: deterministic ranking over a Catalog, no I/O."""

import pytest

from agent_fixtures import make_catalog
from eventssound.adapters.db.seed_data import SEED_ITEMS, SEED_PACKAGES
from eventssound.adapters.search.keyword import KeywordSearch
from eventssound.application.search import EquipmentSearch, InvalidSearch, SearchHit, SearchResult
from eventssound.domain.catalog import (
    Catalog,
    EquipmentCategory,
    EquipmentItem,
    PackageLine,
    ServicePackage,
)
from eventssound.domain.money import Money

CATALOG = make_catalog()
SEARCH = KeywordSearch(CATALOG)


def codes(query: str, category: EquipmentCategory | None = None, limit: int = 5) -> list[str]:
    (result,) = SEARCH.search([query], category, limit)
    return [hit.code for hit in result.hits]


def test_it_satisfies_the_port() -> None:
    assert isinstance(SEARCH, EquipmentSearch)


@pytest.mark.parametrize("query", ["parlante", "bafle", "Altavoz", "PARLÁNTES"])
def test_synonyms_accents_and_plurals_find_the_speaker(query: str) -> None:
    assert "sound_speaker_15" in codes(query)


@pytest.mark.parametrize("query", ["microfono inalambrico", "MICRÓFONO", "micrófonos"])
def test_accents_do_not_matter(query: str) -> None:
    assert "sound_wireless_mic" in codes(query)


def test_zero_width_characters_do_not_hide_a_match() -> None:
    assert "sound_speaker_15" in codes("par\u200blante")


def test_a_package_is_found_through_its_components() -> None:
    result = codes("microfono")

    assert "pkg_party" in result and "sound_wireless_mic" in result


def test_unrelated_queries_return_nothing_and_never_fill_the_limit() -> None:
    assert codes("submarino nuclear") == []


def test_stopwords_only_return_nothing() -> None:
    assert codes("de la en") == []


def test_a_hit_has_a_one_based_rank_a_score_and_no_vector_data() -> None:
    (result,) = SEARCH.search(["parlante"], None, 5)

    assert isinstance(result, SearchResult) and result.degraded is False
    assert [hit.rank for hit in result.hits] == list(range(1, len(result.hits) + 1))
    for hit in result.hits:
        assert isinstance(hit, SearchHit)
        assert hit.kind in {"item", "package"}
        assert 0 < hit.keyword_score <= 1
        assert hit.vector_similarity is None


def test_hits_only_reference_real_codes() -> None:
    real = {i.code for i in CATALOG.items} | {p.code for p in CATALOG.packages}
    for query in ("parlante", "luz", "dj", "humo", "consola"):
        assert set(codes(query, limit=10)) <= real


def test_ties_are_broken_by_item_first_then_ascending_code_whatever_the_catalog_order() -> None:
    items = [
        EquipmentItem(code, "Luz gemela", EquipmentCategory.LIGHTING, 1, Money(1000))
        for code in ("light_zeta", "light_alpha", "light_mid")
    ]
    package = ServicePackage("pkg_aaa", "Paquete", (PackageLine("light_mid", 1),), 0)
    for ordered in (items, items[::-1]):
        search = KeywordSearch(Catalog(tuple(ordered), (package,)))

        (result,) = search.search(["luz gemela"], None, 10)

        assert [h.code for h in result.hits][:3] == ["light_alpha", "light_mid", "light_zeta"]
        assert result.hits[-1].code == "pkg_aaa"  # items outrank packages on equal scores


def test_a_rare_term_weighs_more_than_a_common_one() -> None:
    # "paquete" is in two documents, "humo" in one: matching only the rare word scores higher.
    (result,) = SEARCH.search(["paquete humo"], None, 10)
    scores = {hit.code: hit.keyword_score for hit in result.hits}

    assert scores["fx_fog_machine"] > scores["pkg_party"]


def test_a_full_match_scores_one() -> None:
    (result,) = SEARCH.search(["luz led par rgb"], None, 5)

    assert result.hits[0].code == "light_led_par"
    assert result.hits[0].keyword_score == pytest.approx(1.0)


def test_the_limit_caps_the_hits() -> None:
    assert len(codes("parlante microfono luz", limit=2)) == 2


def test_category_filter_keeps_only_items_of_that_category() -> None:
    assert codes("parlante consola", EquipmentCategory.DJ) == []
    result = codes("parlante consola controlador", EquipmentCategory.SOUND, limit=10)
    assert result and set(result) <= {"sound_speaker_15", "sound_mixer_16", "sound_wireless_mic"}


def test_packages_are_excluded_when_a_category_is_given() -> None:
    assert "pkg_party" in codes("fiesta")
    assert codes("fiesta", EquipmentCategory.SOUND) == []


def test_a_batch_returns_one_result_per_query_in_order() -> None:
    results = SEARCH.search(["humo", "consola", "submarino"], None, 3)

    assert [[h.code for h in r.hits][:1] for r in results] == [
        ["fx_fog_machine"],
        ["sound_mixer_16"],
        [],
    ]


@pytest.mark.parametrize("limit", [0, 11, -1, True, 2.5, "3", None])
def test_invalid_limits_are_rejected(limit: object) -> None:
    with pytest.raises(InvalidSearch):
        SEARCH.search(["luz"], None, limit)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "queries",
    [[], ["  "], ["\u200b"], ["a" * 201], ["x"] * 17, "parlante", [5], b"luz", None],
    ids=["empty-batch", "blank", "zero-width-only", "too-long", "too-many", "bare-string",
         "non-str", "bytes", "none"],
)  # fmt: skip
def test_invalid_queries_are_rejected(queries: object) -> None:
    with pytest.raises(InvalidSearch):
        SEARCH.search(queries, None, 5)  # type: ignore[arg-type]


def test_a_query_of_exactly_200_characters_is_accepted() -> None:
    assert "light_led_par" in codes("luz " + "a" * 196)


def test_an_unknown_category_is_rejected_not_ignored() -> None:
    with pytest.raises(InvalidSearch):
        SEARCH.search(["luz"], "sound", 5)  # type: ignore[arg-type]


def test_an_empty_catalog_never_matches() -> None:
    assert KeywordSearch(Catalog((), ())).search(["luz"], None, 5)[0].hits == ()


# --- retrieval quality (spec: recall@5 >= 0.8 on at least 15 Spanish queries) ---------------

RETRIEVAL_CASES = [
    ("bafle de 12 pulgadas", "sound_active_speaker_12"),
    ("altavoz de 15", "sound_active_speaker_15"),
    ("sub de 18 pulgadas", "sound_subwoofer_18"),
    ("microfonos inalambricos", "sound_wireless_mic"),
    ("luces estroboscopicas", "light_strobe"),
    ("neblina para la pista", "fx_fog_machine"),
    ("mezcladora para dj", "dj_mixer"),
    ("pantalla gigante led", "video_led_screen_3x2"),
    ("escenario", "stage_platform_2x1"),
    ("escalera para subir al escenario", "stage_access_stairs"),
    ("controlador dmx", "light_dmx_controller"),
    ("reproductores cdj", "dj_cdj_pair"),
    ("chispas frias", "fx_cold_spark"),
    ("cabeza movil spot", "light_moving_head_spot"),
    ("consola de 16 canales", "sound_mixer_16ch"),
    ("monitores de piso", "sound_stage_monitor"),
    ("luz par led", "light_led_par"),
    ("line array", "sound_line_array_module"),
    ("Micrófono INALÁMBRICO", "sound_wireless_mic"),
]


def test_keyword_recall_at_5_on_the_seed_catalog() -> None:
    seed = KeywordSearch(Catalog(SEED_ITEMS, SEED_PACKAGES))
    misses = [
        (query, expected)
        for query, expected in RETRIEVAL_CASES
        if expected not in [h.code for h in seed.search([query], None, 5)[0].hits]
    ]

    assert len(RETRIEVAL_CASES) >= 15
    assert 1 - len(misses) / len(RETRIEVAL_CASES) >= 0.8, misses


def test_the_expected_item_ranks_first_for_most_queries() -> None:
    """Recall@5 alone hides packages crowding out the item: also check the rank."""
    seed = KeywordSearch(Catalog(SEED_ITEMS, SEED_PACKAGES))
    ranks = []
    for query, expected in RETRIEVAL_CASES:
        codes_found = [h.code for h in seed.search([query], None, 10)[0].hits]
        ranks.append(codes_found.index(expected) + 1 if expected in codes_found else 99)

    assert sum(rank == 1 for rank in ranks) / len(ranks) >= 0.75, ranks
    assert sum(1 / rank for rank in ranks) / len(ranks) >= 0.85, ranks


@pytest.mark.parametrize("query", ["parlantes", "bafle", "mezcladores", "dos microfonos"])
def test_an_item_outranks_the_packages_that_contain_it(query: str) -> None:
    seed = KeywordSearch(Catalog(SEED_ITEMS, SEED_PACKAGES))

    first = seed.search([query], None, 5)[0].hits[0]

    assert first.kind == "item"


@pytest.mark.parametrize("query", ["moviles", "controladores", "escalones", "cabezas moviles"])
def test_consonant_plurals_reach_their_synonyms(query: str) -> None:
    seed = KeywordSearch(Catalog(SEED_ITEMS, SEED_PACKAGES))

    assert seed.search([query], None, 5)[0].hits


def test_combining_and_variation_marks_do_not_split_a_word() -> None:
    for sneaky in ("par\u034flante", "par\ufe0flante", "par\u180blante"):
        assert codes(sneaky)[:1] == ["sound_speaker_15"], sneaky
