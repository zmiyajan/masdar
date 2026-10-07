"""Resolve the production `SearchService` for the long-running entrypoints.

The API, the MCP server and the image warm-up all need the same fully wired
search pipeline, and only the composition root (``masdar.container``) may
build it. The container's ``default_search_service`` lands in a parallel
change, so it is looked up at call time: entrypoints import and type-check
whether or not it exists yet, and a missing factory fails with a clear
message instead of an ``AttributeError`` deep in startup.
"""

import importlib
from collections.abc import Callable
from typing import cast

from masdar.app.search import SearchService
from masdar.config import Settings
from masdar.domain.errors import MasdarError

_FACTORY_NAME = "default_search_service"


class ServiceUnavailableError(MasdarError):
    """The composition root cannot build the default search pipeline."""


def default_search_service(settings: Settings | None = None) -> SearchService:
    """Build the production search pipeline through the container.

    Args:
        settings: Validated settings; read from the environment when omitted.

    Raises:
        ServiceUnavailableError: If the container has no search factory.
    """
    container = importlib.import_module("masdar.container")
    factory = getattr(container, _FACTORY_NAME, None)
    if not callable(factory):
        raise ServiceUnavailableError(f"masdar.container.{_FACTORY_NAME} is not available")
    build = cast(Callable[[Settings], SearchService], factory)
    return build(settings or Settings())
