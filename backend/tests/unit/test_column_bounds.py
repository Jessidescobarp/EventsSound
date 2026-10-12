"""Domain bounds equal the column sizes, so a valid domain value always fits its column."""

from datetime import UTC, datetime, timedelta

import pytest

from eventssound.domain.availability import Booking, BookingStatus
from eventssound.domain.catalog import (
    MAX_INT32,
    MAX_NAME_LENGTH,
    EquipmentCategory,
    EquipmentItem,
    PackageLine,
    ServicePackage,
)
from eventssound.domain.errors import InvalidAvailability, InvalidCatalog
from eventssound.domain.money import Money

START = datetime(2026, 11, 1, 10, tzinfo=UTC)


def item(name: str = "Equipo", stock: int = 1) -> EquipmentItem:
    return EquipmentItem("abc", name, EquipmentCategory.SOUND, stock, Money(1000))


def package(name: str = "Paquete") -> ServicePackage:
    return ServicePackage("abc", name, (PackageLine("def", 1),))


def booking(quantity: int = 1) -> Booking:
    return Booking("B-1", "abc", quantity, START, START + timedelta(hours=1), BookingStatus.PENDING)


def test_the_bounds_are_the_column_limits() -> None:
    assert MAX_NAME_LENGTH == 120  # VARCHAR(120)
    assert MAX_INT32 == 2**31 - 1  # INTEGER


@pytest.mark.parametrize("build", [item, package], ids=["item", "package"])
def test_names_up_to_the_column_length_are_accepted(build) -> None:
    assert build(name="n" * MAX_NAME_LENGTH).name == "n" * MAX_NAME_LENGTH


@pytest.mark.parametrize("build", [item, package], ids=["item", "package"])
def test_longer_names_are_rejected(build) -> None:
    with pytest.raises(InvalidCatalog):
        build(name="n" * (MAX_NAME_LENGTH + 1))


def test_multibyte_names_are_measured_in_characters() -> None:
    assert item(name="ñ" * MAX_NAME_LENGTH)
    with pytest.raises(InvalidCatalog):
        item(name="ñ" * (MAX_NAME_LENGTH + 1))


@pytest.mark.parametrize(
    "build",
    [
        lambda v: item(stock=v),
        lambda v: PackageLine("abc", v),
        lambda v: booking(quantity=v),
    ],
    ids=["stock", "package-line", "booking"],
)
def test_integer_columns_accept_up_to_int32_and_no_more(build) -> None:
    assert build(MAX_INT32)
    with pytest.raises((InvalidCatalog, InvalidAvailability)):
        build(MAX_INT32 + 1)
