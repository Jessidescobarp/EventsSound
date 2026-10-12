"""Catalog use case."""

from eventssound.application.ports import CatalogRepository
from eventssound.domain.catalog import Catalog


def list_catalog(catalog_repository: CatalogRepository) -> Catalog:
    """The whole catalog. Raises RepositoryUnavailable or InvalidStoredData from the port."""
    return catalog_repository.get_catalog()
