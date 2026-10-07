"""HTTP API and web UI: ``uvicorn masdar.entrypoints.api:create_app --factory``.

The app is thin by design: it validates input, calls `SearchService` (the same
object the CLI, the MCP server and the evaluation use) and presents the result.
The search pipeline is built once at startup, never per request, because
building it means indexing the whole corpus.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from anyio import to_thread
from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from masdar import __version__
from masdar.app.search import SearchService
from masdar.config import Settings
from masdar.container import default_search_service
from masdar.domain.errors import InvalidDomainObjectError, MasdarError
from masdar.domain.search import MAX_QUERY_CHARS
from masdar.entrypoints.laws import LawSummary, load_law_summaries
from masdar.entrypoints.schemas import (
    ErrorBody,
    ErrorResponse,
    HealthResponse,
    SearchResponse,
    to_hit,
)
from masdar.entrypoints.security import RateLimiter, security_headers

WEB_DIR = Path(__file__).parent / "web"
MAX_K = 20
_HEALTH_PATH = "/api/health"
_log = logging.getLogger(__name__)

_ERRORS: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
}


class _UnknownLawError(MasdarError):
    """A ``law`` filter names a law that is not in the corpus."""


def _error(status: int, code: str, message: str, message_ar: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, message_ar=message_ar))
    return JSONResponse(body.model_dump(), status_code=status)


def create_app(
    service: SearchService | None = None,
    settings: Settings | None = None,
    *,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        service: The search pipeline; built from the container at startup
            when omitted (production). Tests inject one.
        settings: Settings; read from the environment when omitted.
        rate_limiter: Per-client limit for ``/api`` routes; 30 requests a
            minute when omitted.
    """
    config = settings or Settings()
    limiter = rate_limiter or RateLimiter()
    laws = load_law_summaries(config.dataset_dir / "stats.json")
    source_urls = {law.law_id: law.source_url for law in laws}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Indexing is CPU-bound and slow; a worker thread keeps the loop free.
        app.state.service = service or await to_thread.run_sync(default_search_service, config)
        yield

    app = FastAPI(
        title="Masdar · مصدر",
        summary="Arabic-first retrieval over Saudi regulations, with citations.",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    _install_middleware(app, limiter)
    _install_error_handlers(app)

    @app.get("/api/health", response_model=HealthResponse, tags=["meta"])
    def health(request: Request) -> HealthResponse:
        """Liveness probe; also names the retrieval pipeline being served."""
        current: SearchService = request.app.state.service
        return HealthResponse(pipeline=current.name, version=__version__)

    @app.get("/api/laws", response_model=list[LawSummary], tags=["search"])
    def list_laws() -> tuple[LawSummary, ...]:
        """The searchable laws, with article counts and snapshot dates."""
        return laws

    @app.get("/api/search", response_model=SearchResponse, responses=_ERRORS, tags=["search"])
    def search(
        request: Request,
        q: Annotated[str, Query(description="The question, in Arabic.")],
        k: Annotated[int, Query(ge=1, le=MAX_K, description="Articles to return.")] = 5,
        law: Annotated[
            list[str] | None, Query(description="Restrict to these law ids (repeatable).")
        ] = None,
    ) -> SearchResponse:
        """Return the ``k`` articles that best answer ``q``, with citations."""
        selected = list(dict.fromkeys(law or ()))
        unknown = [law_id for law_id in selected if law_id not in source_urls]
        if unknown:
            raise _UnknownLawError(", ".join(unknown))
        current: SearchService = request.app.state.service
        results = current.search(q, k=k, laws=selected or None)
        return SearchResponse(
            query=q.strip(),
            k=k,
            laws=selected,
            pipeline=current.name,
            results=[to_hit(result, source_urls) for result in results],
        )

    # Mounted last so that it only serves what no API route matched.
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


def _install_middleware(app: FastAPI, limiter: RateLimiter) -> None:
    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        response: Response
        wait = None
        if path.startswith("/api/") and path != _HEALTH_PATH:
            client = request.client.host if request.client else "unknown"
            wait = limiter.retry_after(client)
        if wait is not None:
            response = _error(
                429,
                "rate_limited",
                f"Too many requests: at most {limiter.limit} per minute. Try again shortly.",
                f"طلبات كثيرة: الحد {limiter.limit} طلباً في الدقيقة. حاول بعد قليل.",
            )
            response.headers["Retry-After"] = str(max(1, round(wait)))
        else:
            response = await call_next(request)
        response.headers.update(security_headers(path))
        return response


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(InvalidDomainObjectError)
    async def invalid_query(_: Request, error: InvalidDomainObjectError) -> JSONResponse:
        return _error(
            422,
            "invalid_query",
            str(error),
            f"السؤال غير صالح: اكتب سؤالاً لا يتجاوز {MAX_QUERY_CHARS} حرف.",
        )

    @app.exception_handler(_UnknownLawError)
    async def unknown_law(_: Request, error: _UnknownLawError) -> JSONResponse:
        return _error(
            422,
            "unknown_law",
            f"Unknown law id: {error}. See /api/laws.",
            "النظام المطلوب غير موجود. راجع قائمة الأنظمة المتاحة.",
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, error: RequestValidationError) -> JSONResponse:
        # Name the offending parameters only; echoing values back is never needed.
        fields = sorted({str(e["loc"][-1]) for e in error.errors() if e.get("loc")})
        return _error(
            422,
            "invalid_request",
            f"Invalid or missing parameters: {', '.join(fields)}. "
            f"q is required; k must be between 1 and {MAX_K}.",
            f"معاملات ناقصة أو غير صالحة: السؤال q مطلوب، وعدد النتائج k بين 1 و{MAX_K}.",
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        # Logged with its traceback for operators; the client never sees it.
        _log.exception("Unhandled error on %s", request.url.path, exc_info=error)
        return _error(
            500,
            "internal_error",
            "Something went wrong on our side. Please try again.",
            "حدث خطأ في الخادم. حاول مرة أخرى.",
        )
