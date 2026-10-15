"""Equipment catalog: items, packages and the validated Catalog aggregate."""

import re
from dataclasses import dataclass, field
from enum import StrEnum

from .errors import CurrencyMismatch, InvalidCatalog, UnknownCatalogEntry
from .money import Money

_CODE = re.compile(r"[a-z0-9_]{3,64}")
MAX_UNIT_PRICE = 1_000_000_000
MAX_NAME_LENGTH = 120  # VARCHAR(120) in the database
MAX_INT32 = 2**31 - 1  # INTEGER in the database


class EquipmentCategory(StrEnum):
    SOUND = "sound"
    LIGHTING = "lighting"
    DJ = "dj"
    STAGE = "stage"
    EFFECTS = "effects"
    VIDEO = "video"
    STAFF = "staff"


def _check_code(code: str) -> None:
    if not isinstance(code, str) or not _CODE.fullmatch(code):
        raise InvalidCatalog("code must match ^[a-z0-9_]{3,64}$")


def _require_int(value: object, name: str) -> int:
    if type(value) is not int:
        raise InvalidCatalog(f"{name} must be an int")
    if value > MAX_INT32:
        raise InvalidCatalog(f"{name} must be at most {MAX_INT32}")
    return value


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not name.strip():
        raise InvalidCatalog("name must not be empty")
    if len(name) > MAX_NAME_LENGTH:
        raise InvalidCatalog(f"name must have at most {MAX_NAME_LENGTH} characters")
    if any(not char.isprintable() for char in name):
        raise InvalidCatalog("name must not contain control characters")  # it reaches LLM prompts


@dataclass(frozen=True, slots=True)
class EquipmentItem:
    """A rentable item. `unit_price` is per rental day."""

    code: str
    name: str
    category: EquipmentCategory
    stock_quantity: int
    unit_price: Money

    def __post_init__(self) -> None:
        _check_code(self.code)
        _check_name(self.name)
        if not isinstance(self.category, EquipmentCategory):
            raise InvalidCatalog("category must be an EquipmentCategory")
        if _require_int(self.stock_quantity, "stock_quantity") < 0:
            raise InvalidCatalog("stock_quantity must be >= 0")
        if not isinstance(self.unit_price, Money):
            raise InvalidCatalog("unit_price must be Money")
        if not 0 <= self.unit_price.amount <= MAX_UNIT_PRICE:
            raise InvalidCatalog(f"unit_price must be within 0..{MAX_UNIT_PRICE}")


@dataclass(frozen=True, slots=True)
class PackageLine:
    item_code: str
    quantity: int

    def __post_init__(self) -> None:
        if _require_int(self.quantity, "quantity") < 1:
            raise InvalidCatalog("package line quantity must be >= 1")


@dataclass(frozen=True, slots=True)
class ServicePackage:
    """A bundle of items. It has no price of its own: it is derived from its lines."""

    code: str
    name: str
    lines: tuple[PackageLine, ...]
    discount_bps: int = 0

    def __post_init__(self) -> None:
        _check_code(self.code)
        _check_name(self.name)
        object.__setattr__(self, "lines", tuple(self.lines))
        if not self.lines:
            raise InvalidCatalog("a package needs at least one line")
        codes = [line.item_code for line in self.lines]
        if len(set(codes)) != len(codes):
            raise InvalidCatalog("package lines must reference distinct items")
        if not 0 <= _require_int(self.discount_bps, "discount_bps") <= 10_000:
            raise InvalidCatalog("discount_bps must be within 0..10000")

    def base_unit_price(self, catalog: "Catalog") -> Money:
        """Sum of member prices per rental day, before discount."""
        prices = [(catalog.item(line.item_code).unit_price, line.quantity) for line in self.lines]
        # Sum in the members' currency (lines are never empty); mixed currencies still raise.
        return Money.sum((price * qty for price, qty in prices), prices[0][0].currency)


@dataclass(frozen=True, slots=True)
class Catalog:
    items: tuple[EquipmentItem, ...]
    packages: tuple[ServicePackage, ...]
    _items: dict[str, EquipmentItem] = field(init=False, repr=False, compare=False)
    _packages: dict[str, ServicePackage] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "packages", tuple(self.packages))
        currencies = {item.unit_price.currency for item in self.items}
        if len(currencies) > 1:
            raise CurrencyMismatch("all item prices must share one currency")
        items = {item.code: item for item in self.items}
        packages = {package.code: package for package in self.packages}
        if len(items) != len(self.items):
            raise InvalidCatalog("duplicate item codes")
        if len(packages) != len(self.packages):
            raise InvalidCatalog("duplicate package codes")
        for package in self.packages:
            for line in package.lines:
                if line.item_code not in items:
                    raise UnknownCatalogEntry(line.item_code)
        object.__setattr__(self, "_items", items)
        object.__setattr__(self, "_packages", packages)

    def item(self, code: str) -> EquipmentItem:
        try:
            return self._items[code]
        except KeyError:
            raise UnknownCatalogEntry(code) from None

    def package(self, code: str) -> ServicePackage:
        try:
            return self._packages[code]
        except KeyError:
            raise UnknownCatalogEntry(code) from None
