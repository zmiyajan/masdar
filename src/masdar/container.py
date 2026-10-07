"""Composition root: the only module that builds adapters and wires use cases.

Keeping all construction here means use cases never know which concrete
adapters they run with, and tests can wire fakes the same way.
"""

import ssl
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import truststore

from masdar.adapters.beir_writer import BeirDatasetWriter
from masdar.adapters.boe.client import BoeClient
from masdar.adapters.boe.source import BoeLawSource
from masdar.adapters.gold_jsonl import JsonlGoldSource
from masdar.app.build_dataset import BuildDataset
from masdar.app.corpus import Corpus, load_corpus
from masdar.config import Settings
from masdar.domain.arabic import ArabicNormalizer
from masdar.domain.chunking import ChunkingOptions


@contextmanager
def dataset_builder(
    settings: Settings, *, offline: bool = False, refresh: bool = False
) -> Iterator[BuildDataset]:
    """Yield a ready `BuildDataset`; the HTTP client is closed on exit.

    Args:
        settings: Validated application settings.
        offline: Use only the committed snapshots; never touch the network.
        refresh: Re-download every page (ignored when ``offline``).
    """
    # The portal does not send its intermediate certificate, so certifi's bundle
    # cannot build the chain. The OS trust store can (it fetches intermediates);
    # verification stays fully on. See ADR-0002.
    tls = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with httpx.Client(
        headers={"User-Agent": settings.user_agent},
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
        verify=tls,
    ) as http:
        client = BoeClient(
            http,
            settings.snapshot_dir,
            crawl_delay=settings.crawl_delay_seconds,
            offline=offline,
        )
        yield BuildDataset(
            source=BoeLawSource(client, settings.snapshot_dir, refresh=refresh and not offline),
            writer=BeirDatasetWriter(settings.dataset_dir),
            normalizer=ArabicNormalizer(),
            chunking=ChunkingOptions(),
            gold=JsonlGoldSource(settings.gold_path),
        )


def load_current_corpus(settings: Settings) -> Corpus:
    """Current articles and chunks, built offline from the committed snapshots.

    Retrievers, the API, the MCP server and the evaluation all index exactly
    this corpus, so they agree on what "the law" is.
    """
    with httpx.Client() as http:
        client = BoeClient(
            http, settings.snapshot_dir, crawl_delay=settings.crawl_delay_seconds, offline=True
        )
        source = BoeLawSource(client, settings.snapshot_dir)
        return load_corpus(source, ArabicNormalizer(), ChunkingOptions())
