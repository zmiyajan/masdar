"""The small entrypoint components: rate limiter, presentation, runtime, warm-up."""

import pytest

import masdar.container
from masdar.app.search import SearchService
from masdar.domain.amendments import Amendment, AmendmentKind, HijriDate
from masdar.entrypoints import warmup
from masdar.entrypoints.runtime import ServiceUnavailableError, default_search_service
from masdar.entrypoints.schemas import latest_amendment
from masdar.entrypoints.security import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestRateLimiter:
    def test_window_slides(self) -> None:
        clock = Clock()
        limiter = RateLimiter(limit=2, window_seconds=60, clock=clock)
        assert limiter.retry_after("a") is None
        clock.now += 30
        assert limiter.retry_after("a") is None
        assert limiter.retry_after("a") == pytest.approx(30)
        clock.now += 30  # the first request leaves the window
        assert limiter.retry_after("a") is None
        assert limiter.retry_after("a") == pytest.approx(30)

    def test_clients_are_independent(self) -> None:
        limiter = RateLimiter(limit=1, clock=Clock())
        assert limiter.retry_after("a") is None
        assert limiter.retry_after("b") is None
        assert limiter.retry_after("a") is not None

    def test_memory_is_bounded(self) -> None:
        clock = Clock()
        limiter = RateLimiter(limit=1, window_seconds=60, clock=clock, max_clients=2)
        limiter.retry_after("a")
        limiter.retry_after("b")
        limiter.retry_after("c")  # evicts the oldest client, "a"
        assert limiter.retry_after("a") is None
        clock.now += 61  # everyone is idle now; idle clients go first
        for key in ("d", "e"):
            assert limiter.retry_after(key) is None

    @pytest.mark.parametrize("kwargs", [{"limit": 0}, {"window_seconds": 0}, {"max_clients": 0}])
    def test_rejects_non_positive_bounds(self, kwargs: dict[str, float]) -> None:
        with pytest.raises(ValueError, match="positive"):
            RateLimiter(**kwargs)  # type: ignore[arg-type]


def note(decree: str, issued: HijriDate | None) -> Amendment:
    return Amendment(AmendmentKind.REPLACE, "n", decree, issued)


class TestLatestAmendment:
    def test_none_without_amendments(self) -> None:
        assert latest_amendment(()) is None

    def test_latest_date_wins_over_position(self) -> None:
        new, old = note("م/2", HijriDate(1446, 1, 1)), note("م/1", HijriDate(1440, 1, 1))
        assert latest_amendment((new, old, note("م/3", None))) is new

    def test_same_date_goes_to_the_later_note(self) -> None:
        first, second = note("م/1", HijriDate(1446, 1, 1)), note("م/2", HijriDate(1446, 1, 1))
        assert latest_amendment((first, second)) is second

    def test_undated_falls_back_to_publication_order(self) -> None:
        first, second = note("م/1", None), note("م/2", None)
        assert latest_amendment((first, second)) is second


class TestRuntime:
    def test_delegates_to_the_container(
        self, service: SearchService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            masdar.container, "default_search_service", lambda _: service, raising=False
        )
        assert default_search_service() is service

    def test_missing_factory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delattr(masdar.container, "default_search_service", raising=False)
        with pytest.raises(ServiceUnavailableError):
            default_search_service()


def test_warmup_builds_and_queries_the_pipeline(
    service: SearchService, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(warmup, "default_search_service", lambda _: service)
    assert warmup.main() == 0
    assert "warm-up: fake ready" in capsys.readouterr().out
