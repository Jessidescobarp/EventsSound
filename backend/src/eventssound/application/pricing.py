"""Pricing use case: prices come from the deterministic domain function, never from a model."""

from eventssound.application.ports import CatalogRepository
from eventssound.domain.event_request import EventRequest
from eventssound.domain.pricing import Quote, calculate_price
from eventssound.domain.pricing_rules import PricingRules


def price_quote(
    request: EventRequest, catalog_repository: CatalogRepository, rules: PricingRules
) -> Quote:
    return calculate_price(request, catalog_repository.get_catalog(), rules)
