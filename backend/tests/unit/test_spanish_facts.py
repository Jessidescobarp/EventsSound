import pytest

from eventssound.application.spanish_facts import (
    parse_clock_time,
    parse_duration_hours,
    parse_guest_count,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a las 8 PM", "20:00"),
        ("8:30 p. m.", "20:30"),
        ("12 am", "00:00"),
        ("12 pm", "12:00"),
        ("20:00", "20:00"),
        ("20:00:00", "20:00"),
        ("10 km", None),
        ("el 5 de noviembre", None),
        ("13 pm", None),
    ],
)
def test_parse_clock_time(text: str, expected: str | None) -> None:
    assert parse_clock_time(text) == expected


@pytest.mark.parametrize(
    ("text", "guests", "hours"),
    [
        ("cumpleanos de 60 personas por 4 horas", 60, 4.0),
        ("120 invitados, 5,5 horas", 120, 5.5),
        ("Paquete Boda", None, None),
        ("0 personas, 100 horas", None, None),
    ],
)
def test_parse_guest_count_and_duration(text: str, guests: int | None, hours: float | None) -> None:
    assert parse_guest_count(text) == guests
    assert parse_duration_hours(text) == hours
