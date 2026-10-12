"""Availability use case."""

from eventssound.application.ports import BookingRepository, CatalogRepository
from eventssound.domain.availability import (
    AvailabilityReport,
    AvailabilityRules,
    booking_search_window,
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
    the query window is the domain's own buffer-widened window (absolute time, range-checked).
    """
    catalog = catalog_repository.get_catalog()
    window_start, window_end = booking_search_window(request.start, request.end, rules)
    bookings = booking_repository.find_reservations(
        set(required_units(request, catalog)), window_start, window_end
    )
    return check_request_availability(request, catalog, bookings, rules)
