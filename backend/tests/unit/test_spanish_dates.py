"""Spanish day+month parsing: accents, case, year rollover, invalid dates, garbage."""

from datetime import date

import pytest

from eventssound.application.spanish_dates import parse_spanish_date

TODAY = date(2026, 10, 22)


@pytest.mark.parametrize(
    ("text", "today", "expected"),
    [
        ("el 15 de diciembre", TODAY, date(2026, 12, 15)),
        ("5 DE NOVIEMBRE", TODAY, date(2026, 11, 5)),
        ("5 nov", TODAY, date(2026, 11, 5)),
        ("15/12", TODAY, date(2026, 12, 15)),
        ("el 3 de Setiembre", TODAY, date(2027, 9, 3)),
        ("22 de octubre", TODAY, date(2026, 10, 22)),
        ("21 de octubre", TODAY, date(2027, 10, 21)),
        ("5 de enero", date(2026, 12, 20), date(2027, 1, 5)),
        ("29 de febrero", date(2026, 3, 1), date(2028, 2, 29)),
        ("15 de diciembre de 2026", TODAY, date(2026, 12, 15)),
        ("15 de diciembre del 2027", TODAY, date(2027, 12, 15)),
        ("15/12/2027", TODAY, date(2027, 12, 15)),
        ("el 5 de enero y luego 9 de mayo", TODAY, date(2027, 1, 5)),
        ("31 de febrero", TODAY, None),
        ("31 de febrero o el 2 de marzo", TODAY, date(2027, 3, 2)),
        ("32/13", TODAY, None),
        ("a las 5 PM con 120 personas", TODAY, None),
        ("5 martes", TODAY, None),
        ("", TODAY, None),
    ],
)
def test_parse_spanish_date(text: str, today: date, expected: date | None) -> None:
    assert parse_spanish_date(text, today) == expected
