"""Polite, cached HTTP access to laws.boe.gov.sa.

Every page is stored as a gzip snapshot (``<law_id>.html.gz``) of the exact
bytes received, next to a small manifest (``<law_id>.json``: URL, fetch date,
SHA-256 of those bytes). The snapshot directory is committed, so the dataset
rebuilds offline and reproducibly; the portal is contacted only on ``refresh``,
and never more often than the crawl delay allows.
"""

import gzip
import hashlib
import json
import time
import zlib
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from masdar.adapters.boe.catalog import BoeLaw
from masdar.adapters.files import write_atomically
from masdar.domain.errors import SourceFetchError, SourceFormatError

_PAGE_MARKER = "article_item"  # every law page contains article blocks


def _utc_today() -> date:
    return datetime.now(UTC).date()


class BoeClient:
    """Fetches law pages, honouring the crawl delay and keeping gzip snapshots."""

    def __init__(  # noqa: PLR0913 - collaborators are injected for testability
        self,
        http: httpx.Client,
        snapshot_dir: Path,
        *,
        crawl_delay: float,
        offline: bool = False,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        today: Callable[[], date] = _utc_today,
    ) -> None:
        """Create a client.

        Args:
            http: The HTTP client (inject a mock transport in tests).
            snapshot_dir: Where page snapshots and manifests are stored.
            crawl_delay: Minimum seconds between two requests to the portal.
            offline: Never touch the network; only serve snapshots.
            clock: Monotonic clock, injectable for tests.
            sleep: Sleep function, injectable for tests.
            today: Date recorded in manifests, injectable for tests.
        """
        self._http = http
        self._snapshot_dir = snapshot_dir
        self._crawl_delay = crawl_delay
        self._offline = offline
        self._clock = clock
        self._sleep = sleep
        self._today = today
        self._last_request: float | None = None

    def fetch(
        self,
        law: BoeLaw,
        *,
        refresh: bool = False,
        validate: Callable[[str], object] | None = None,
    ) -> str:
        """Return the law page HTML, from the snapshot unless ``refresh`` is set.

        Args:
            law: The law to fetch.
            refresh: Download even if a snapshot exists.
            validate: Called on a freshly downloaded page *before* it replaces
                the snapshot; it should raise if the page is unusable, so a
                broken download can never overwrite a good snapshot.

        Raises:
            SourceFetchError: If there is no snapshot in offline mode, or the
                request fails.
            SourceFormatError: If the page or its snapshot is not a valid law page.
        """
        snapshot = self._snapshot_dir / f"{law.law_id}.html.gz"
        if snapshot.exists() and not refresh:
            return _read_snapshot(snapshot)
        if self._offline:
            raise SourceFetchError(f"No snapshot for {law.law_id} and offline mode is on")

        raw = self._download(law)
        html = _decode(raw, law.url)
        if _PAGE_MARKER not in html:
            raise SourceFormatError(f"{law.url} did not return a law page")
        if validate is not None:
            validate(html)
        self._save_snapshot(law, raw)
        return html

    def _download(self, law: BoeLaw) -> bytes:
        self._wait_for_crawl_delay()
        try:
            response = self._http.get(law.url)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise SourceFetchError(f"Could not fetch {law.url}: {error}") from error
        finally:
            self._last_request = self._clock()
        return response.content

    def _wait_for_crawl_delay(self) -> None:
        if self._last_request is None:
            return
        remaining = self._crawl_delay - (self._clock() - self._last_request)
        if remaining > 0:
            self._sleep(remaining)

    def _save_snapshot(self, law: BoeLaw, raw: bytes) -> None:
        manifest = {
            "law_id": law.law_id,
            "url": law.url,
            "fetched_on": self._today().isoformat(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        # mtime=0 keeps the gzip bytes identical for identical pages.
        write_atomically(self._snapshot_dir / f"{law.law_id}.html.gz", gzip.compress(raw, mtime=0))
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        write_atomically(self._snapshot_dir / f"{law.law_id}.json", manifest_text.encode())


def _decode(raw: bytes, origin: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceFormatError(f"{origin} is not valid UTF-8: {error}") from error


def _read_snapshot(path: Path) -> str:
    try:
        raw = gzip.decompress(path.read_bytes())
    except (OSError, EOFError, zlib.error) as error:  # BadGzipFile is an OSError
        raise SourceFormatError(f"Corrupt snapshot {path}: {error}") from error
    return _decode(raw, str(path))


def read_manifest(snapshot_dir: Path, law_id: str) -> dict[str, str]:
    """Return a snapshot's manifest (url, fetched_on, sha256), or ``{}`` if absent.

    Raises:
        SourceFormatError: If the manifest exists but is not a JSON object.
    """
    path = snapshot_dir / f"{law_id}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SourceFormatError(f"Corrupt manifest {path}: {error}") from error
    if not isinstance(data, dict):
        raise SourceFormatError(f"Manifest {path} is not a JSON object")
    return {str(key): str(value) for key, value in data.items()}
