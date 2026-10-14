"""Deterministic Spanish template and the system's own Spanish strings."""

from datetime import datetime
from zoneinfo import ZoneInfo

from eventssound.application.messages_es import (
    CLARIFICATION_FIELD_ORDER,
    REFUSAL,
    render_clarification,
)
from eventssound.application.proposal_check import QuoteFacts, render_template
from eventssound.domain.availability import Availability
from quote_fixtures import CANARY, facts, golden

TZ = ZoneInfo("America/Bogota")


class TestGoldenWorkedExample:
    def test_the_domain_worked_example_still_reconciles(self) -> None:
        quote, _, _ = golden()
        assert quote.subtotal.amount == 538_855
        assert quote.total.amount == 539_000

    def test_facts_from_quote(self) -> None:
        quote, request, catalog = golden()
        f = QuoteFacts.from_quote(quote, request, catalog, canary=CANARY)
        assert f.total == 539_000
        assert f.subtotal == 538_855
        assert len(f.lines) == 7
        by_code = {line.code: line for line in f.lines}
        assert by_code["sound_speaker_active_15"].amount == 240_000
        assert f.catalog_names["sound_mixer_16ch"] == "Mezcladora 16 canales"


class TestRenderTemplate:
    def test_golden_quote_renders_every_line(self) -> None:
        text = render_template(facts())
        assert "el sabado 17 de octubre de 2026" in text
        assert "de 8:00 p. m. a 11:30 p. m." in text
        assert "con 150 invitados" in text
        assert "- 2 x Parlante activo 15 pulgadas: $240.000 COP" in text
        assert "- 1 x Mezcladora 16 canales: $79.900 COP" in text
        assert "- Recargo por numero de invitados (10%): $31.990 COP" in text
        assert "- Recargo fin de semana (15%): $47.985 COP" in text
        assert "- Recargo horario nocturno (20%): $63.980 COP" in text
        assert "- Transporte (25 km): $75.000 COP" in text
        assert "- Ajuste de redondeo: $145 COP" in text
        assert "Total: $539.000 COP" in text
        assert text.endswith("Los valores los calcula nuestro sistema de precios.")

    def test_plain_text_only(self) -> None:
        text = render_template(facts())
        assert "<" not in text and "http" not in text and "[" not in text

    def test_amounts_are_thousands_formatted(self) -> None:
        from eventssound.application.proposal_check import FactLine, LineKind

        f = facts(
            lines=(
                FactLine("x", "Equipo grande", 3, LineKind.ITEM, 411_855, None, None, 1_235_565),
                FactLine("rounding", None, 1, LineKind.ROUNDING, None, None, None, 435),
            ),
            subtotal=1_235_565,
            total=1_236_000,
        )
        text = render_template(f)
        assert "- 3 x Equipo grande: $1.235.565 COP" in text
        assert "Total: $1.236.000 COP" in text

    def test_zero_rounding_is_omitted(self) -> None:
        from eventssound.application.proposal_check import FactLine, LineKind

        f = facts(
            lines=(FactLine("x", "Equipo", 1, LineKind.ITEM, 100_000, None, None, 100_000),),
            subtotal=100_000,
            total=100_000,
        )
        assert "redondeo" not in render_template(f)

    def test_negative_rounding_is_shown_with_a_sign(self) -> None:
        from eventssound.application.proposal_check import FactLine, LineKind

        f = facts(
            lines=(
                FactLine("x", "Equipo", 1, LineKind.ITEM, 100_145, None, None, 100_145),
                FactLine("rounding", None, 1, LineKind.ROUNDING, None, None, None, -145),
            ),
            subtotal=100_145,
            total=100_000,
        )
        assert "- Ajuste de redondeo: -$145 COP" in render_template(f)

    def test_multi_day_event(self) -> None:
        f = facts(
            start=datetime(2026, 10, 17, 20, 0, tzinfo=TZ),
            end=datetime(2026, 10, 18, 2, 0, tzinfo=TZ),
        )
        assert "del 17 de octubre al 18 de octubre de 2026" in render_template(f)

    def test_morning_times_use_a_m(self) -> None:
        f = facts(
            start=datetime(2026, 10, 17, 9, 0, tzinfo=TZ),
            end=datetime(2026, 10, 17, 13, 30, tzinfo=TZ),
        )
        assert "de 9:00 a. m. a 1:30 p. m." in render_template(f)

    def test_package_lines_use_the_package_name(self) -> None:
        from eventssound.application.proposal_check import FactLine, LineKind

        f = facts(
            lines=(
                FactLine(
                    "pkg", "Paquete Fiesta", 1, LineKind.PACKAGE, 250_000, None, None, 250_000
                ),
            ),
            subtotal=250_000,
            total=250_000,
            catalog_names={"pkg": "Paquete Fiesta"},
        )
        assert "- 1 x Paquete Fiesta: $250.000 COP" in render_template(f)

    def test_shortages_are_listed_with_units(self) -> None:
        from eventssound.application.proposal_check import ShortageFact

        f = facts(
            shortages=(
                ShortageFact("sound_speaker_active_15", "Parlante activo 15 pulgadas", 4, 2),
            )
        )
        text = render_template(f)
        assert "No pudimos garantizar todo el equipo:" in text
        assert "- Parlante activo 15 pulgadas: pediste 4, hay 2." in text


class TestRefusalAndClarification:
    def test_refusal_is_the_pinned_design_text(self) -> None:
        assert REFUSAL == (
            "Solo puedo ayudarte a cotizar equipos de sonido, luces y DJ para eventos."
            " Cuentame que evento tienes en mente: tipo, fecha, numero de invitados y lugar."
        )

    def test_clarification_asks_at_most_three_fields_in_priority_order(self) -> None:
        text = render_clarification(["equipment", "guest_count", "event_date", "start_time"])

        assert text == (
            "Para armar tu cotizacion necesito algunos datos mas:\n"
            "1. Que fecha va a ser el evento?\n"
            "2. A que hora empieza?\n"
            "3. Cuantos invitados habra?"
        )

    def test_every_field_has_a_spanish_template(self) -> None:
        for code in CLARIFICATION_FIELD_ORDER:
            assert render_clarification([code]).count("1. ") == 1

    def test_an_unknown_field_code_is_rejected(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            render_clarification(["zip_code"])

    def test_an_empty_request_is_rejected(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            render_clarification([])


class TestAvailabilityShortageShape:
    def test_shortage_fact_is_frozen(self) -> None:
        from eventssound.application.proposal_check import ShortageFact

        s = ShortageFact("a", "b", 2, 1)
        assert s.requested == 2 and s.available == 1

    def test_domain_availability_is_unused_by_the_template(self) -> None:
        # The template renders ShortageFact, never the domain object (keeps the port pure).
        from eventssound.application.proposal_check import ShortageFact

        assert issubclass(Availability, object)
        assert ShortageFact("a", "b", 1, 0).item_code == "a"


class TestClarifyItems:
    def test_ambiguous_mentions_list_catalog_names_only(self) -> None:
        from eventssound.application.messages_es import render_clarify_items

        text = render_clarify_items(
            (("parlantes", ("Parlante activo de 15 pulgadas", "Paquete DJ")),), ()
        )
        assert "parlantes" in text
        assert "Parlante activo de 15 pulgadas" in text
        assert "o" in text

    def test_three_options_are_joined_with_o(self) -> None:
        from eventssound.application.messages_es import render_clarify_items

        text = render_clarify_items((("luces", ("Luz LED PAR RGB", "Luz A", "Luz B")),), ())
        assert "Luz LED PAR RGB, Luz A o Luz B" in text

    def test_unresolved_mentions_say_not_found(self) -> None:
        from eventssound.application.messages_es import render_clarify_items

        text = render_clarify_items((), ("tarima gigante",))
        assert "tarima gigante" in text
        assert "catalogo" in text

    def test_mixed_ambiguous_and_unresolved(self) -> None:
        from eventssound.application.messages_es import render_clarify_items

        text = render_clarify_items((("dj", ("Controlador DJ de 4 canales",)),), ("humo",))
        assert "dj" in text and "humo" in text

    def test_rephrase_constant_is_static_spanish(self) -> None:
        from eventssound.application.messages_es import CLARIFICATION_REPHRASE

        assert isinstance(CLARIFICATION_REPHRASE, str)
        assert len(CLARIFICATION_REPHRASE) > 20


class TestFactsPayload:
    def test_payload_covers_the_draft_contract(self) -> None:
        from eventssound.application.proposal_check import facts_payload

        quote, request, _ = golden()
        payload = facts_payload(
            QuoteFacts.from_quote(quote, request, _, canary=CANARY),
            event_type="wedding",
            available=True,
        )
        assert payload["event_type"] == "wedding"
        assert payload["guest_count"] == request.guest_count
        assert payload["total_cop"] == quote.total.amount
        assert payload["date"].startswith("el ") or payload["date"].startswith("del ")
        assert payload["start"] == "8:00 p. m."
        assert payload["availability"] == "disponible"
        assert all("amount_cop" in line for line in payload["lines"])

    def test_every_line_is_described_in_spanish_including_surcharges(self) -> None:
        from eventssound.application.proposal_check import facts_payload

        quote, request, availability = golden()
        facts = QuoteFacts.from_quote(quote, request, availability, canary=CANARY)

        payload = facts_payload(facts, event_type="wedding", available=True)

        from eventssound.application.proposal_check import _line_bullets

        texts = [line["text"] for line in payload["lines"]]
        assert texts == [bullet[2:] for bullet in _line_bullets(facts)]
        assert all("None" not in text for text in texts)
