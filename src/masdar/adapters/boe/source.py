"""`LawSource` implementation backed by laws.boe.gov.sa."""

import dataclasses
from pathlib import Path

from masdar.adapters.boe.catalog import CATALOG, find_law
from masdar.adapters.boe.client import BoeClient, read_manifest
from masdar.adapters.boe.parser import parse_law_html
from masdar.domain.articles import PublishedLaw


class BoeLawSource:
    """Loads laws from the Bureau of Experts portal (implements `LawSource`)."""

    def __init__(self, client: BoeClient, snapshot_dir: Path, *, refresh: bool = False) -> None:
        """Create the source.

        Args:
            client: Fetches (and snapshots) the law pages.
            snapshot_dir: The client's snapshot directory, read for provenance.
            refresh: Re-download pages even when a snapshot exists.
        """
        self._client = client
        self._snapshot_dir = snapshot_dir
        self._refresh = refresh

    def law_ids(self) -> tuple[str, ...]:
        """Slugs of every law this source can load."""
        return tuple(law.law_id for law in CATALOG)

    def load(self, law_id: str) -> PublishedLaw:
        """Fetch and parse one law.

        Raises:
            UnknownLawError: If ``law_id`` is not in the catalog.
            SourceFetchError: If the page cannot be fetched.
            SourceFormatError: If the page structure is not recognized.
        """
        law = find_law(law_id)

        def parse(html: str) -> PublishedLaw:
            return parse_law_html(html, law_id=law.law_id, source_url=law.url)

        # Parsing also validates a fresh download before it replaces the snapshot.
        published = parse(self._client.fetch(law, refresh=self._refresh, validate=parse))
        retrieved_on = read_manifest(self._snapshot_dir, law.law_id).get("fetched_on")
        return dataclasses.replace(published, retrieved_on=retrieved_on)
