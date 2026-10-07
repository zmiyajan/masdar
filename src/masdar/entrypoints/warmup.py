"""Pre-build the search pipeline: ``python -m masdar.entrypoints.warmup``.

The Docker image runs this at build time so that model weights (and any index
the container caches on disk) are inside the image. Without it, the first
visitor to a cold Space would wait for downloads and indexing.
"""

import sys
import time

from masdar.config import Settings
from masdar.container import default_search_service

_WARMUP_QUESTION = "كم مدة إجازة الأمومة؟"


def main() -> int:
    """Build the pipeline once and run one query through it; return the exit code."""
    started = time.perf_counter()
    service = default_search_service(Settings())
    results = service.search(_WARMUP_QUESTION, k=1)
    elapsed = time.perf_counter() - started
    print(f"warm-up: {service.name} ready in {elapsed:.1f}s ({len(results)} result)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
