"""Catalog edits made by an admin: the write port and the service that wraps it.

The domain objects are the only input, so every rule of `EquipmentItem` and `ServicePackage`
holds before anything is stored. Items are never deleted (bookings and packages point at them):
an item that is no longer offered gets stock 0. A code never changes after creation.
"""

import logging
from collections.abc import Callable
from typing import Protocol

from eventssound.domain.catalog import EquipmentItem, ServicePackage

logger = logging.getLogger(__name__)


class CatalogWriter(Protocol):
    """Raises CodeTaken on a duplicate code, NotFound when the entry to update is missing,
    UnknownCatalogEntry when a package line names an unknown item, and RepositoryUnavailable on
    storage failure."""

    def create_item(self, item: EquipmentItem) -> None: ...

    def update_item(self, item: EquipmentItem) -> None: ...

    def create_package(self, package: ServicePackage) -> None: ...

    def update_package(self, package: ServicePackage) -> None: ...


class CatalogAdmin:
    """Writes the catalog, then tells the rest of the app it changed (search index, agent).

    `on_changed` is best effort: the write already happened, so a failure is logged, never raised.
    """

    def __init__(self, writer: CatalogWriter, on_changed: Callable[[], None]) -> None:
        self._writer = writer
        self._on_changed = on_changed

    def create_item(self, item: EquipmentItem) -> None:
        self._writer.create_item(item)
        self._changed("item_created", item.code)

    def update_item(self, item: EquipmentItem) -> None:
        self._writer.update_item(item)
        self._changed("item_updated", item.code)

    def create_package(self, package: ServicePackage) -> None:
        self._writer.create_package(package)
        self._changed("package_created", package.code)

    def update_package(self, package: ServicePackage) -> None:
        self._writer.update_package(package)
        self._changed("package_updated", package.code)

    def _changed(self, action: str, code: str) -> None:
        logger.info("catalog %s code=%s", action, code)
        try:
            self._on_changed()
        except Exception as error:  # noqa: BLE001 - best effort by design, see class docstring
            logger.warning("catalog change hook failed error=%s", type(error).__name__)
