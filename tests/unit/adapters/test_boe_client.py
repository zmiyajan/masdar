"""Tests for the BOE client: snapshots, crawl delay and errors. No network."""

import gzip
import hashlib
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from masdar.adapters.boe.catalog import BoeLaw, find_law
from masdar.adapters.boe.client import BoeClient, read_manifest
from masdar.domain.errors import SourceFetchError, SourceFormatError, UnknownLawError

LAW = BoeLaw("labor-law", "guid-1")
OTHER = BoeLaw("pdpl", "guid-2")
PAGE = '<div class="article_item">نص</div>'


class FakeTime:
    """A controllable monotonic clock that records sleeps."""

    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(
    tmp_path: Path,
    handler: httpx.MockTransport,
    *,
    offline: bool = False,
    time: FakeTime | None = None,
) -> BoeClient:
    fake = time or FakeTime()
    return BoeClient(
        httpx.Client(transport=handler),
        tmp_path,
        crawl_delay=10.0,
        offline=offline,
        clock=fake.clock,
        sleep=fake.sleep,
        today=lambda: date(2026, 10, 7),
    )


def ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=PAGE)


def test_downloads_once_then_serves_the_snapshot(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return ok(request)

    client = make_client(tmp_path, httpx.MockTransport(handler))
    assert client.fetch(LAW) == PAGE
    assert client.fetch(LAW) == PAGE
    assert calls == [LAW.url]


def test_snapshot_is_gzip_with_a_manifest(tmp_path: Path) -> None:
    make_client(tmp_path, httpx.MockTransport(ok)).fetch(LAW)
    assert gzip.decompress((tmp_path / "labor-law.html.gz").read_bytes()).decode() == PAGE
    assert read_manifest(tmp_path, "labor-law") == {
        "law_id": "labor-law",
        "url": LAW.url,
        "fetched_on": "2026-10-07",
        "sha256": hashlib.sha256(PAGE.encode()).hexdigest(),
    }
    assert not list(tmp_path.glob("*.partial"))


def test_refresh_downloads_again(tmp_path: Path) -> None:
    pages = iter([PAGE, PAGE + "<!-- v2 -->"])
    client = make_client(
        tmp_path, httpx.MockTransport(lambda _: httpx.Response(200, text=next(pages)))
    )
    client.fetch(LAW)
    assert client.fetch(LAW, refresh=True).endswith("v2 -->")


def test_waits_for_the_crawl_delay_between_requests(tmp_path: Path) -> None:
    time = FakeTime()
    client = make_client(tmp_path, httpx.MockTransport(ok), time=time)
    client.fetch(LAW)
    time.now += 3.0
    client.fetch(OTHER)
    assert time.sleeps == [pytest.approx(7.0)]


def test_offline_mode_never_touches_the_network(tmp_path: Path) -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise AssertionError("network used in offline mode")

    with pytest.raises(SourceFetchError, match="offline"):
        make_client(tmp_path, httpx.MockTransport(fail), offline=True).fetch(LAW)


@pytest.mark.parametrize(
    ("response", "error"),
    [
        pytest.param(httpx.Response(503), SourceFetchError, id="server-error"),
        pytest.param(
            httpx.Response(200, text="<html>maintenance</html>"),
            SourceFormatError,
            id="not-a-law-page",
        ),
    ],
)
def test_bad_responses_raise_and_leave_no_snapshot(
    tmp_path: Path, response: httpx.Response, error: type[Exception]
) -> None:
    client = make_client(tmp_path, httpx.MockTransport(lambda _: response))
    with pytest.raises(error):
        client.fetch(LAW)
    assert not (tmp_path / "labor-law.html.gz").exists()


def test_connection_errors_are_wrapped(tmp_path: Path) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    with pytest.raises(SourceFetchError, match="unreachable"):
        make_client(tmp_path, httpx.MockTransport(down)).fetch(LAW)


def test_missing_manifest_reads_as_empty(tmp_path: Path) -> None:
    assert read_manifest(tmp_path, "nothing") == {}


def test_catalog_lookup() -> None:
    assert find_law("pdpl").url.endswith("/b7cfae89-828e-4994-b167-adaa00e37188/1")
    with pytest.raises(UnknownLawError, match="known laws"):
        find_law("tax-law")


def test_manifest_file_is_valid_json(tmp_path: Path) -> None:
    make_client(tmp_path, httpx.MockTransport(ok)).fetch(LAW)
    assert json.loads((tmp_path / "labor-law.json").read_text())["law_id"] == "labor-law"


def test_failed_validation_keeps_the_existing_snapshot(tmp_path: Path) -> None:
    client = make_client(tmp_path, httpx.MockTransport(ok))
    client.fetch(LAW)
    before = (tmp_path / "labor-law.html.gz").read_bytes()

    def reject(_: str) -> None:
        raise SourceFormatError("parser rejected the page")

    with pytest.raises(SourceFormatError, match="rejected"):
        client.fetch(LAW, refresh=True, validate=reject)
    assert (tmp_path / "labor-law.html.gz").read_bytes() == before


def test_manifest_hashes_the_bytes_exactly_as_received(tmp_path: Path) -> None:
    raw = PAGE.encode("utf-8")
    make_client(tmp_path, httpx.MockTransport(lambda _: httpx.Response(200, content=raw))).fetch(
        LAW
    )
    assert read_manifest(tmp_path, "labor-law")["sha256"] == hashlib.sha256(raw).hexdigest()
    assert gzip.decompress((tmp_path / "labor-law.html.gz").read_bytes()) == raw


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param(b"not gzip", "Corrupt snapshot", id="bad-gzip"),
        pytest.param(gzip.compress(b"\xff\xfe"), "not valid UTF-8", id="bad-encoding"),
    ],
)
def test_corrupt_snapshot_raises_a_clear_error(
    tmp_path: Path, content: bytes, message: str
) -> None:
    (tmp_path / "labor-law.html.gz").write_bytes(content)
    client = make_client(tmp_path, httpx.MockTransport(ok), offline=True)
    with pytest.raises(SourceFormatError, match=message):
        client.fetch(LAW)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param(b"{not json", "Corrupt manifest", id="bad-json"),
        pytest.param(b"[1, 2]", "not a JSON object", id="not-an-object"),
    ],
)
def test_corrupt_manifest_raises_a_clear_error(
    tmp_path: Path, content: bytes, message: str
) -> None:
    (tmp_path / "labor-law.json").write_bytes(content)
    with pytest.raises(SourceFormatError, match=message):
        read_manifest(tmp_path, "labor-law")


def test_invalid_utf8_download_is_rejected(tmp_path: Path) -> None:
    bad = httpx.MockTransport(lambda _: httpx.Response(200, content=b"article_item \xff"))
    with pytest.raises(SourceFormatError, match="UTF-8"):
        make_client(tmp_path, bad).fetch(LAW)
