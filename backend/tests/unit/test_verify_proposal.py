"""verify_proposal: every rule from design D25, fail-closed, stable reason codes."""

import pytest

from eventssound.application.proposal_check import (
    VerificationResult,
    render_template,
    verify_proposal,
)
from quote_fixtures import CANARY, facts


def base_text() -> str:
    """A valid draft that is not the template itself (LLM-style phrasing)."""
    return (
        "Hola, para tu evento del sabado 17 de octubre de 2026 de 8:00 p. m. a 11:30 p. m."
        " con 150 invitados la propuesta es: 2 x Parlante activo 15 pulgadas por $240.000 COP,"
        " 1 x Mezcladora 16 canales por $79.900 COP, recargo por numero de invitados (10%)"
        " de $31.990 COP, recargo fin de semana (15%) de $47.985 COP, recargo horario nocturno"
        " (20%) de $63.980 COP y transporte (25 km) de $75.000 COP. Con un ajuste de redondeo"
        " de $145 COP, el total es de $539.000 COP. Los valores los calcula nuestro sistema."
    )


class TestVerificationResult:
    def test_shape(self) -> None:
        r = VerificationResult(True, ())
        assert r.ok is True and r.reasons == ()


class TestValidDrafts:
    def test_llm_style_draft_passes(self) -> None:
        assert verify_proposal(base_text(), facts()).ok

    def test_template_passes_by_construction(self) -> None:
        f = facts()
        result = verify_proposal(render_template(f), f)
        assert result.ok and result.reasons == ()

    def test_template_passes_with_shortages(self) -> None:
        from eventssound.application.proposal_check import ShortageFact

        f = facts(
            shortages=(
                ShortageFact("sound_speaker_active_15", "Parlante activo 15 pulgadas", 4, 2),
            )
        )
        assert verify_proposal(render_template(f), f).ok

    def test_iso_date_and_24h_times_are_accepted(self) -> None:
        f = facts()
        text = (
            base_text()
            .replace("17 de octubre de 2026", "2026-10-17")
            .replace("8:00 p. m.", "20:00")
        )
        assert verify_proposal(text, f).ok


class TestLengthAndControls:
    def test_too_short(self) -> None:
        assert verify_proposal("Hola, $539.000 COP.", facts()).reasons == ("length",)

    def test_too_long(self) -> None:
        text = base_text() + " " + "x" * 1600
        assert "length" in verify_proposal(text, facts()).reasons

    def test_control_characters_fail(self) -> None:
        text = base_text().replace("total", "tot\x07al")
        assert "length" in verify_proposal(text, facts()).reasons


class TestForbiddenContent:
    @pytest.mark.parametrize(
        "snippet",
        [
            "ver http://example.com para mas info",
            "visita www.example.com hoy",
            "escribime a ventas@eventos.com",
            "[clic aqui](http://example.com)",
            "![logo](http://img.com/a.png)",
            "<b>oferta especial</b> solo hoy",
            "llamame al 3123456789 ahora",
            "mi usuario es @eventosdj en redes",
        ],
    )
    def test_forbidden_snippets(self, snippet: str) -> None:
        text = base_text() + " " + snippet
        result = verify_proposal(text, facts())
        assert result.ok is False
        assert "url" in result.reasons


class TestCanaryAndSentinels:
    def test_canary_fails(self) -> None:
        assert "canary" in verify_proposal(base_text() + f" {CANARY}", facts()).reasons

    def test_sentinel_phrase_is_case_and_accent_insensitive(self) -> None:
        f = facts(sentinel_phrases=("Solo citas, nunca das consejos legales",))
        text = base_text() + " Recuerda: SOLO CITAS, NUNCA DAS CONSEJOS LEGALES ok."
        assert "canary" in verify_proposal(text, f).reasons

    def test_sentinel_absent_passes(self) -> None:
        f = facts(sentinel_phrases=("no inventes precios",))
        assert verify_proposal(base_text(), f).ok


class TestNumbers:
    def test_unknown_money_amount_fails(self) -> None:
        text = base_text().replace("$539.000 COP. Los", "$999.999 COP. Los")
        result = verify_proposal(text, facts())
        assert "unknown_amount" in result.reasons

    def test_fact_amounts_are_accepted(self) -> None:
        f = facts()
        for amount in (240_000, 79_900, 31_990, 47_985, 63_980, 75_000, 145, 538_855, 539_000):
            text = base_text().replace("$539.000", f"${amount:,}".replace(",", "."))
            result = verify_proposal(text, f)
            assert "unknown_amount" not in result.reasons, amount

    def test_millions_word_amount(self) -> None:
        f = facts(total=1_500_000, subtotal=1_500_000)
        text = base_text().replace("$539.000", "1,5 millones")
        assert verify_proposal(text, f).ok

    def test_kiloword_amount(self) -> None:
        f = facts(total=539_000, subtotal=539_000)
        text = base_text().replace("$539.000", "539 mil pesos")
        assert verify_proposal(text, f).ok

    def test_spanish_number_words_with_currency_fail_closed(self) -> None:
        text = base_text().replace("$539.000 COP", "quinientos treinta y nueve mil pesos")
        assert "unknown_amount" in verify_proposal(text, facts()).reasons

    def test_unknown_bare_number_fails(self) -> None:
        text = base_text().replace("con 150 invitados", "con 37 invitados")
        assert "unknown_number" in verify_proposal(text, facts()).reasons

    def test_allowed_numbers_pass(self) -> None:
        f = facts()
        for n in (150, 2, 1, 10, 15, 20, 25, 15, 16, 2026, 1):
            text = base_text().replace("transporte (25 km)", f"transporte ({n} km)")
            result = verify_proposal(text, f)
            assert "unknown_number" not in result.reasons, n

    def test_decimal_number_fails_closed(self) -> None:
        text = base_text().replace("(10%)", "(10.5%)")
        assert "unknown_number" in verify_proposal(text, facts()).reasons


class TestTotal:
    def test_missing_total_fails(self) -> None:
        text = base_text().replace("el total es de $539.000 COP", "el total final queda confirmado")
        result = verify_proposal(text, facts())
        assert "missing_total" in result.reasons


class TestDates:
    def test_wrong_named_date_fails(self) -> None:
        text = base_text().replace("17 de octubre", "18 de octubre")
        assert "unknown_date" in verify_proposal(text, facts()).reasons

    def test_slash_date_accepted_and_wrong_slash_fails(self) -> None:
        f = facts()
        assert verify_proposal(base_text().replace("17 de octubre de 2026", "17/10/2026"), f).ok
        assert (
            "unknown_date"
            in verify_proposal(
                base_text().replace("17 de octubre de 2026", "17/11/2026"), f
            ).reasons
        )

    def test_end_date_is_also_accepted(self) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        f = facts(end=datetime(2026, 10, 18, 2, 0, tzinfo=ZoneInfo("America/Bogota")))
        text = (
            base_text().replace("11:30 p. m.", "2:00 a. m.")
            + " El evento termina el 18 de octubre de 2026."
        )
        assert verify_proposal(text, f).ok


class TestTimes:
    def test_wrong_clock_time_fails(self) -> None:
        text = base_text().replace("8:00 p. m.", "9:00 a. m.")
        assert "unknown_time" in verify_proposal(text, facts()).reasons

    def test_word_time_matches_start(self) -> None:
        assert verify_proposal(base_text().replace("8:00 p. m.", "8 p. m."), facts()).ok

    def test_word_time_mismatch_fails(self) -> None:
        text = base_text().replace("8:00 p. m.", "9 p. m.")
        assert "unknown_time" in verify_proposal(text, facts()).reasons


class TestItems:
    def test_catalog_entry_not_in_quote_fails(self) -> None:
        f = facts(catalog_names={**facts().catalog_names, "pkg_fiesta": "Paquete Fiesta"})
        text = base_text() + " Incluye el Paquete Fiesta completo de regalo."
        assert "unknown_item" in verify_proposal(text, f).reasons

    def test_quoted_entries_pass(self) -> None:
        assert verify_proposal(base_text(), facts()).ok


class TestReviewRegressions:
    def test_event_ending_after_midnight_renders_and_passes(self) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from eventssound.application.proposal_check import render_template

        f = facts(end=datetime(2026, 10, 18, 0, 30, tzinfo=ZoneInfo("America/Bogota")))
        assert verify_proposal(render_template(f), f).ok

    def test_wrong_meridiem_on_noon_time_fails(self) -> None:
        text = base_text().replace("8:00 p. m.", "12:30 a. m.")
        assert "unknown_time" in verify_proposal(text, facts()).reasons

    @pytest.mark.parametrize(
        "bad_date",
        ["31 de febrero de 2026", "31/02/2026", "2026-02-31"],
    )
    def test_calendar_impossible_dates_fail_closed_without_crash(self, bad_date: str) -> None:
        text = base_text().replace("17 de octubre de 2026", bad_date)
        assert "unknown_date" in verify_proposal(text, facts()).reasons

    def test_canary_in_other_casing_is_caught(self) -> None:
        text = base_text() + f" {CANARY.upper()}"
        assert "canary" in verify_proposal(text, facts()).reasons

    def test_shortage_with_zero_available_renders_and_passes(self) -> None:
        from eventssound.application.proposal_check import ShortageFact, render_template

        f = facts(shortages=(ShortageFact("spk-15", "Parlante activo 15 pulgadas", 4, 0),))
        assert verify_proposal(render_template(f), f).ok

    def test_non_integer_rate_percent_renders_and_passes(self) -> None:
        from dataclasses import replace

        from eventssound.application.proposal_check import render_template

        lines = tuple(
            replace(line, rate_bps=1050) if line.rate_bps == 1000 else line
            for line in facts().lines
        )
        f = facts(lines=lines)
        assert verify_proposal(render_template(f), f).ok

    def test_word_amount_with_de_and_singular_millon_fails(self) -> None:
        text = base_text() + " El total seria de tres millones de pesos."
        assert "unknown_amount" in verify_proposal(text, facts()).reasons

    def test_distance_km_from_facts_is_allowed(self) -> None:
        text = base_text().replace("transporte (25 km)", "transporte a 45 km")
        assert verify_proposal(text, facts()).ok


class TestReasons:
    def test_multiple_reasons_are_reported_deduplicated_in_check_order(self) -> None:
        f = facts(canary="esd-canary")
        text = base_text().replace("17 de octubre", "18 de octubre") + " esd-canary http://x.com"
        result = verify_proposal(text, f)
        assert result.reasons == ("url", "canary", "unknown_date")

    def test_reasons_never_echo_user_text(self) -> None:
        text = base_text() + " http://secreto-unico-zzz.com"
        assert "secreto-unico-zzz" not in str(verify_proposal(text, facts()).reasons)
