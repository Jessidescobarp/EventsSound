"""Availability use case."""

from eventssound.application.ports import BookingRepository, CatalogRepository
from eventssound.domain.availability import (
    AvailabilityReport,
    AvailabilityRules,
    check_request_availability,
    required_units,
)
from eventssound.domain.event_request import EventRequest


def check_event_availability(
    request: EventRequest,
    catalog_repository: CatalogRepository,
    booking_repository: BookingRepository,
    rules: AvailabilityRules,
) -> AvailabilityReport:
    """Check every item the request needs.

    The domain counts a booking as concurrent when it falls inside the buffer around the event, so
    the query window is widened by the buffer on both sides.
    """
    catalog = catalog_repository.get_catalog()
    bookings = booking_repository.find_reservations(
        set(required_units(request, catalog)),
        request.start - rules.buffer,
        request.end + rules.buffer,
    )
    return check_request_availability(request, catalog, bookings, rules)
