"""Runtime settings, read from environment variables (prefix ``MASDAR_``).

Settings are validated when the application starts, so a bad value fails fast
with a clear message instead of surfacing deep inside a run.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# laws.boe.gov.sa robots.txt: "Crawl-delay: 10". Policy, so it lives here.
ROBOTS_CRAWL_DELAY_SECONDS = 10.0


class Settings(BaseSettings):
    """Application settings.

    Attributes:
        snapshot_dir: Gzip snapshots of the source pages (committed to git).
        dataset_dir: Where ``make dataset`` writes the BEIR corpus and card.
        gold_path: The gold question set (JSON Lines, one question per line).
        crawl_delay_seconds: Pause between portal requests; robots.txt asks for
            at least 10 seconds, so lower values are rejected.
        http_timeout_seconds: Timeout for one portal request.
        user_agent: Identifies Masdar to the portal.
        eval_dir: Where ``masdar eval`` writes results, ``RESULTS.md`` and the baseline.
        index_dir: Cache of corpus embeddings (gitignored, safe to delete).
        pipeline: The search pipeline the CLI, API and MCP server serve; one of
            ``masdar.container.PIPELINES``. ``bm25`` runs without the ``ml`` extra.
        trusted_proxy_hops: Reverse proxies in front of the app that append to
            ``X-Forwarded-For``. The rate limit keys on the entry the nearest
            trusted proxy wrote; entries further left are client-controlled.
            ``0`` (default) uses the socket peer and ignores the header.
    """

    model_config = SettingsConfigDict(env_prefix="MASDAR_", env_file=".env", extra="ignore")

    snapshot_dir: Path = Path("data/sources/boe")
    dataset_dir: Path = Path("data/dataset")
    gold_path: Path = Path("data/gold/queries.v1.jsonl")
    crawl_delay_seconds: float = Field(
        default=ROBOTS_CRAWL_DELAY_SECONDS, ge=ROBOTS_CRAWL_DELAY_SECONDS
    )
    http_timeout_seconds: float = Field(default=30.0, gt=0)
    user_agent: str = "masdar/0.1 (Arabic legal retrieval research)"
    eval_dir: Path = Path("eval")
    index_dir: Path = Path("data/index")
    pipeline: str = "dense+rerank"
    trusted_proxy_hops: int = Field(default=0, ge=0)
