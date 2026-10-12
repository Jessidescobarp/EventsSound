"""Catalog entities: validation, lookups and derived package price."""

import dataclasses
from collections.abc import Callable

import pytest

from eventssound.domain.catalog import (
    Catalog,
    EquipmentCategory,
    EquipmentItem,
    PackageLine,
    ServicePackage,
)
from eventssound.domain.errors import InvalidCatalog, UnknownCatalogEntry
from eventssound.domain.money import Money


def make_item(
    code: str = "sound_speaker",
    *,
    name: str = "Parlante",
    stock: int = 4,
    price: int = 120000,
    category: EquipmentCategory = EquipmentCategory.SOUND,
) -> EquipmentItem:
    return EquipmentItem(code, name, category, stock, Money(price))


def make_package(
    code: str = "pkg_basic", lines: tuple[PackageLine, ...] | None = None, discount_bps: int = 0
) -> ServicePackage:
    lines = lines if lines is not None else (PackageLine("sound_speaker", 2),)
    return ServicePackage(code, "Basico", lines, discount_bps)


def test_categories_match_the_design() -> None:
    assert [c.value for c in EquipmentCategory] == [
        "sound",
        "lighting",
        "dj",
        "stage",
        "effects",
        "video",
    ]


@pytest.mark.parametrize("code", ["ab", "Sound_x", "has space", "a" * 65, "dash-ed", ""])
def test_invalid_item_code_is_rejected(code: str) -> None:
    with pytest.raises(InvalidCatalog):
        make_item(code)


@pytest.mark.parametrize(
    "overrides",
    [
        {"stock": -1},
        {"price": -1},
        {"price": 1_000_000_001},
        {"name": "  "},
    ],
    ids=["negative-stock", "negative-price", "price-over-cap", "blank-name"],
)
def test_invalid_item_fields_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(InvalidCatalog):
        make_item(**overrides)  # type: ignore[arg-type]


def test_item_accepts_boundary_values() -> None:
    item = make_item(stock=0, price=1_000_000_000)

    assert item.stock_quantity == 0
    assert item.unit_price == Money(1_000_000_000)


def test_entities_are_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        make_item().stock_quantity = 9  # type: ignore[misc]


@pytest.mark.parametrize(
    "build",
    [
        lambda: make_package(lines=()),
        lambda: make_package(
            lines=(PackageLine("sound_speaker", 1), PackageLine("sound_speaker", 2))
        ),
        lambda: make_package(discount_bps=-1),
        lambda: make_package(discount_bps=10_001),
        lambda: PackageLine("sound_speaker", 0),
    ],
    ids=["no-lines", "duplicate-item", "discount-negative", "discount-over-100", "zero-quantity"],
)
def test_invalid_package_is_rejected(build: Callable[[], object]) -> None:
    with pytest.raises(InvalidCatalog):
        build()


def test_package_accepts_full_discount() -> None:
    assert make_package(discount_bps=10_000).discount_bps == 10_000


def test_duplicate_codes_are_rejected() -> None:
    with pytest.raises(InvalidCatalog):
        Catalog((make_item(), make_item()), ())
    with pytest.raises(InvalidCatalog):
        Catalog((make_item(),), (make_package(), make_package()))


def test_package_referencing_unknown_item_is_rejected() -> None:
    with pytest.raises(UnknownCatalogEntry) as error:
        Catalog((make_item("sound_mixer"),), (make_package(),))

    assert "sound_speaker" in str(error.value)


def test_lookup_by_code() -> None:
    item, package = make_item(), make_package()
    catalog = Catalog((item,), (package,))

    assert catalog.item("sound_speaker") is item
    assert catalog.package("pkg_basic") is package


def test_lookup_of_unknown_code_names_it() -> None:
    catalog = Catalog((make_item(),), ())

    with pytest.raises(UnknownCatalogEntry, match="nope"):
        catalog.item("nope")
    with pytest.raises(UnknownCatalogEntry, match="pkg_nope"):
        catalog.package("pkg_nope")


def test_package_base_unit_price_is_derived_from_members() -> None:
    catalog = Catalog(
        (make_item("sound_speaker", price=120000), make_item("sound_mixer", price=79900)),
        (make_package(lines=(PackageLine("sound_speaker", 2), PackageLine("sound_mixer", 1))),),
    )

    assert catalog.package("pkg_basic").base_unit_price(catalog) == Money(319900)
