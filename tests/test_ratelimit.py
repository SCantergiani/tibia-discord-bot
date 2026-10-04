import pytest

from tibiabot.ratelimit import AdaptiveRate


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def __call__(self):
        return self.t

    async def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.t += seconds


def limiter(clock, **kw):
    return AdaptiveRate(start=2, ceiling=4, clock=clock, **kw)


async def test_requests_are_spaced_one_over_the_rate_apart():
    clock = Clock()
    rate = limiter(clock)
    for _ in range(3):
        await rate.acquire(clock.sleep)
    assert clock.slept == [0.5, 0.5]


def test_pushback_halves_the_rate_and_pauses():
    clock = Clock()
    rate = limiter(clock)
    rate.on_pushback(429)
    assert rate.rate == 1 and rate.paused


def test_a_burst_of_errors_counts_once():
    clock = Clock()
    rate = limiter(clock)
    for status in (429, 503, 403):
        rate.on_pushback(status)
    assert rate.rate == 1


def test_never_below_the_floor_or_on_ordinary_errors():
    clock = Clock()
    rate = limiter(clock, pause_seconds=0)
    for _ in range(10):
        rate.on_pushback(429)
        clock.t += 1
    assert rate.rate == 0.25
    rate.on_pushback(500)  # not a sign of being throttled
    assert rate.rate == 0.25


async def test_no_request_goes_out_during_the_pause():
    clock = Clock()
    rate = limiter(clock, pause_seconds=60)
    rate.on_pushback(429)
    await rate.acquire(clock.sleep)
    assert clock.slept == [60]


async def test_climbs_slowly_while_quiet_up_to_the_ceiling():
    clock = Clock()
    rate = limiter(clock, quiet_seconds=600, step=0.25)
    clock.t = 599
    await rate.acquire(clock.sleep)
    assert rate.rate == 2
    clock.t += 1
    await rate.acquire(clock.sleep)
    assert rate.rate == 2.25
    for _ in range(20):
        clock.t += 600
        await rate.acquire(clock.sleep)
    assert rate.rate == 4


def test_start_is_clamped_between_floor_and_ceiling():
    assert AdaptiveRate(start=10, ceiling=4).rate == 4
    assert AdaptiveRate(start=0, ceiling=4).rate == 0.25
