from datetime import date

import pytest

from eventssound.application.answer_binding import parse_field_answer, pick_option
from eventssound.application.messages_es import (
    asked_fields,
    clarified_mentions,
    render_clarification,
    render_clarify_items,
)
from eventssound.application.spanish_facts import parse_clock_times, parse_duration_hours

TODAY = date(2026, 10, 12)


@pytest.mark.parametrize(
    ("field", "text", "expected"),
    [
        ("end_time_or_duration", "5", {"duration_hours": 5.0}),
        ("end_time_or_duration", "5 horas", {"duration_hours": 5.0}),
        ("end_time_or_duration", "cinco horas", {"duration_hours": 5.0}),
        ("end_time_or_duration", "4h", {"duration_hours": 4.0}),
        ("end_time_or_duration", "1 hora", {"duration_hours": 1.0}),
        ("end_time_or_duration", "11 PM", {"end_time": "23:00"}),
        ("end_time_or_duration", "23:00", {"end_time": "23:00"}),
        ("end_time_or_duration", "hasta las 11 pm", {"end_time": "23:00"}),
        ("end_time_or_duration", "hasta las 11", {"end_time": "11:00"}),
        ("end_time_or_duration", "100", {}),
        ("start_time", "8", {"start_time": "08:00"}),
        ("start_time", "8 PM", {"start_time": "20:00"}),
        ("start_time", "a las 8:30 pm", {"start_time": "20:30"}),
        ("start_time", "25", {}),
        ("guest_count", "60", {"guest_count": 60}),
        ("guest_count", "60 personas", {"guest_count": 60}),
        ("guest_count", "0", {}),
        ("distance_or_locality", "10", {"distance_km": 10}),
        ("distance_or_locality", "10 km", {"distance_km": 10}),
        ("distance_or_locality", "10KM", {"distance_km": 10}),
        ("distance_or_locality", "aprox 12 kilometros", {"distance_km": 12}),
        ("event_date", "5 de noviembre", {"event_date": "2026-11-05"}),
        # a number is only read for the field being asked; sentences and other fields bind nothing
        ("event_date", "10", {}),
        ("equipment", "5", {}),
        ("guest_count", "cuanto cuesta 60 pesos de lo que sea que quieras decirme hoy", {}),
        ("guest_count", "hola", {}),
    ],
)
def test_parse_field_answer(field: str, text: str, expected: dict) -> None:
    assert parse_field_answer(field, text, TODAY) == expected


def test_pick_option_is_accent_and_case_insensitive() -> None:
    names = ("Paquete Fiesta Básica", "Paquete Boda")
    assert pick_option("  paquete fiesta basica ", names) == "Paquete Fiesta Básica"
    assert pick_option("paquete boda y mas", names) is None


def test_clarification_texts_round_trip() -> None:
    assert asked_fields(render_clarification(("start_time", "guest_count"))) == (
        "start_time",
        "guest_count",
    )
    assert asked_fields("Cotiza esto\n1. A que hora empieza?") == ()  # no intro: not ours
    items = render_clarify_items((("sonido", ("A", "B")),), ("xyz",))
    assert clarified_mentions(items) == ("sonido", "xyz")
    assert clarified_mentions(render_clarification(("start_time",))) is None


def test_clock_times_and_singular_hour() -> None:
    assert parse_clock_times("de 8 PM a 11:30 pm") == ["20:00", "23:30"]
    assert parse_duration_hours("por 1 hora") == 1.0
