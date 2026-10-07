"""HTTP API and web UI: ``uvicorn masdar.entrypoints.api:create_app --factory``.

The app is thin by design: it validates input, calls `SearchService` (the same
object the CLI, the MCP server and the evaluation use) and presents the result.
The search pipeline is built once at startup, never per request, because
building it means indexing the whole corpus.
"""

import logging
import math
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from anyio import to_thread
from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from masdar import __version__
from masdar.app.answer import AnswerService
from masdar.app.check_contract import CheckContract
from masdar.app.search import SearchService
from masdar.config import Settings
from masdar.container import answer_service, check_contract_use_case, default_search_service
from masdar.domain.errors import InvalidDomainObjectError, MasdarError
from masdar.domain.search import MAX_QUERY_CHARS
from masdar.entrypoints.laws import LawSummary, load_law_summaries
from masdar.entrypoints.schemas import (
    AnswerResponse,
    CheckRequest,
    CheckResponse,
    ErrorBody,
    ErrorResponse,
    HealthResponse,
    SearchResponse,
    to_answer,
    to_check,
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


class _AnswersUnavailableError(MasdarError):
    """The served pipeline has no cross-encoder, so answers are not offered."""


def _error(status: int, code: str, message: str, message_ar: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, message_ar=message_ar))
    return JSONResponse(body.model_dump(), status_code=status)


def create_app(
    service: SearchService | None = None,
    settings: Settings | None = None,
    *,
    answers: AnswerService | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        service: The search pipeline; built from the container at startup
            when omitted (production). Tests inject one.
        settings: Settings; read from the environment when omitted.
        answers: The answer service; derived from ``service`` when omitted
            (none for pipelines without a cross-encoder). Tests inject one.
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
        app.state.answers = answers if answers is not None else answer_service(app.state.service)
        app.state.checker = check_contract_use_case(app.state.service)
        yield

    app = FastAPI(
        title="Masdar · مصدر",
        summary="Arabic-first retrieval over Saudi regulations, with citations.",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    _install_middleware(app, limiter, config.trusted_proxy_hops)
    _install_error_handlers(app)

    @app.get("/api/health", response_model=HealthResponse, tags=["meta"])
    def health(request: Request) -> HealthResponse:
        """Liveness probe; also names the retrieval pipeline being served."""
        current: SearchService = request.app.state.service
        return HealthResponse(
            pipeline=current.name,
            answers=request.app.state.answers is not None,
            version=__version__,
        )

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
        selected = _known_laws(law, source_urls)
        current: SearchService = request.app.state.service
        results = current.search(q, k=k, laws=selected or None)
        return SearchResponse(
            query=q.strip(),
            k=k,
            laws=selected,
            pipeline=current.name,
            results=[to_hit(result, source_urls) for result in results],
        )

    @app.get("/api/answer", response_model=AnswerResponse, responses=_ERRORS, tags=["search"])
    def answer(
        request: Request,
        q: Annotated[str, Query(description="The question, in Arabic.")],
        k: Annotated[int, Query(ge=1, le=MAX_K, description="Related articles to return.")] = 5,
        law: Annotated[
            list[str] | None, Query(description="Restrict to these law ids (repeatable).")
        ] = None,
    ) -> AnswerResponse:
        """Quote the sentence of the law that answers ``q``, or say none does.

        The quote is copied from the article in force, never generated; below a
        calibrated confidence the status is ``not_found`` (ADR-0009).
        """
        selected = _known_laws(law, source_urls)
        current: AnswerService | None = request.app.state.answers
        if current is None:
            raise _AnswersUnavailableError
        result = current.answer(q, laws=selected or None, related=k)
        return to_answer(result, selected, current.name, source_urls)

    @app.post("/api/check", response_model=CheckResponse, responses=_ERRORS, tags=["check"])
    def check(request: Request, body: CheckRequest) -> CheckResponse:
        """Check a contract or HR policy, clause by clause, against the Labor Law in force.

        Verdicts come from rules pinned to the articles' text in force, never
        from a model; anything uncertain is ``review_needed`` (ADR-0010).
        """
        selected = _known_laws(body.laws, source_urls)
        checker: CheckContract = request.app.state.checker
        return to_check(checker.run(body.text, laws=selected or None), source_urls)

    # After every real route: anything else under /api is an unknown route.
    @app.api_route(
        "/api/{rest:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def unknown_api_route(rest: str) -> JSONResponse:  # noqa: ARG001 - matched, not used
        """Keep unknown ``/api`` paths in the JSON error envelope, not the static 404."""
        return _error(404, "not_found", "No such API route.", "لا يوجد مسار بهذا الاسم.")

    # Mounted last so that it only serves what no API route matched.
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


def _known_laws(law: list[str] | None, source_urls: Mapping[str, str]) -> list[str]:
    selected = list(dict.fromkeys(law or ()))
    unknown = [law_id for law_id in selected if law_id not in source_urls]
    if unknown:
        raise _UnknownLawError(", ".join(unknown))
    return selected


def client_key(request: Request, trusted_proxy_hops: int) -> str:
    """The address the rate limit counts against.

    Each trusted proxy appends the address it received the request from, so the
    entry ``trusted_proxy_hops`` from the right was written by our own edge.
    Anything to its left was sent by the client and can be forged.

    Args:
        request: The incoming request.
        trusted_proxy_hops: Proxies in front of the app (``Settings``).
    """
    peer = request.client.host if request.client else "unknown"
    if trusted_proxy_hops == 0:
        return peer
    forwarded = [
        entry.strip()
        for header in request.headers.getlist("x-forwarded-for")
        for entry in header.split(",")
        if entry.strip()
    ]
    return forwarded[-trusted_proxy_hops] if len(forwarded) >= trusted_proxy_hops else peer


def _install_middleware(app: FastAPI, limiter: RateLimiter, trusted_proxy_hops: int) -> None:
    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        response: Response
        wait = None
        if path.startswith("/api/") and path != _HEALTH_PATH:
            wait = limiter.retry_after(client_key(request, trusted_proxy_hops))
        if wait is not None:
            response = _error(
                429,
                "rate_limited",
                f"Too many requests: at most {limiter.limit} per minute. Try again shortly.",
                f"طلبات كثيرة: الحد {limiter.limit} طلباً في الدقيقة. حاول بعد قليل.",
            )
            response.headers["Retry-After"] = str(max(1, math.ceil(wait)))
        else:
            try:
                response = await call_next(request)
            except Exception:
                # Handled here, inside the guard, so a 500 still carries the
                # security headers. Logged with its traceback for operators;
                # the client never sees it.
                _log.exception("Unhandled error on %s", path)
                response = _error(
                    500,
                    "internal_error",
                    "Something went wrong on our side. Please try again.",
                    "حدث خطأ في الخادم. حاول مرة أخرى.",
                )
        response.headers.update(security_headers(path))
        return response


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(InvalidDomainObjectError)
    async def invalid_query(request: Request, error: InvalidDomainObjectError) -> JSONResponse:
        if request.url.path == "/api/check":
            return _error(
                422,
                "invalid_document",
                str(error),
                "النص فارغ أو أطول من المسموح (20,000 حرف).",
            )
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

    @app.exception_handler(_AnswersUnavailableError)
    async def answers_unavailable(_: Request, __: _AnswersUnavailableError) -> JSONResponse:
        return _error(
            501,
            "answers_unavailable",
            "This deployment serves search only; answers need the reranked pipeline.",
            "هذه النسخة تقدّم البحث فقط، والإجابة المقتبسة غير متاحة فيها.",
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        # Name the offending parameters only; echoing values back is never needed.
        fields = sorted({str(e["loc"][-1]) for e in error.errors() if e.get("loc")})
        if request.url.path == "/api/check":
            return _error(
                422,
                "invalid_request",
                f"Invalid or missing fields: {', '.join(fields)}. "
                "Send JSON with text (up to 20,000 characters) and optional laws.",
                "أرسل نص العقد أو السياسة (حتى 20,000 حرف).",
            )
        return _error(
            422,
            "invalid_request",
            f"Invalid or missing parameters: {', '.join(fields)}. "
            f"q is required; k must be between 1 and {MAX_K}.",
            f"معاملات ناقصة أو غير صالحة: السؤال q مطلوب، وعدد النتائج k بين 1 و{MAX_K}.",
        )
