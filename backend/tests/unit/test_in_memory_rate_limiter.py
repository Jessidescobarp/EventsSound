"""InMemoryRateLimiter: boundary, isolation, sliding window, hourly cap, memory bound."""

import pytest

from eventssound.adapters.usage.rate_limit import InMemoryRateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(**kwargs):
    clock = Clock()
    return InMemoryRateLimiter(kwargs.pop("per_minute", 3), clock=clock, **kwargs), clock


def test_nth_request_passes_and_the_next_is_denied_with_retry_after() -> None:
    limiter, clock = make()
    assert [limiter.hit("a").allowed for _ in range(3)] == [True, True, True]
    clock.now += 10
    denied = limiter.hit("a")
    assert not denied.allowed and denied.retry_after_seconds == 51  # oldest hit leaves at +60 s
    assert limiter.hit("b").allowed  # another client is unaffected


def test_window_slides_and_denied_hits_are_not_recorded() -> None:
    limiter, clock = make()
    for _ in range(3):
        limiter.hit("a")
    for _ in range(50):
        assert not limiter.hit("a").allowed  # hammering does not extend the lockout
    clock.now += 61
    assert limiter.hit("a").allowed


def test_hourly_cap_and_global_key_have_their_own_limits() -> None:
    limiter, clock = make(per_minute=2, per_hour=3, global_per_minute=5)
    allowed = 0
    for _ in range(4):
        allowed += limiter.hit("a").allowed
        clock.now += 61  # the minute window never binds; the hour window does
    assert allowed == 3
    assert [limiter.hit("*").allowed for _ in range(6)] == [True] * 5 + [False]


def test_tracked_keys_are_bounded_and_fail_closed() -> None:
    limiter, _ = make(max_keys=10)
    results = [limiter.hit(f"ip-{i}").allowed for i in range(50)]
    assert results.count(True) == 10 and len(limiter._hits) == 10


@pytest.mark.parametrize("key", ["", None, 5])
def test_invalid_key_is_a_typed_error(key) -> None:
    with pytest.raises(ValueError):
        make()[0].hit(key)


def test_invalid_limits_are_rejected() -> None:
    with pytest.raises(ValueError):
        InMemoryRateLimiter(0)
