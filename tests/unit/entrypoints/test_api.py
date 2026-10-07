"""HTTP API tests: a real SearchService over a fake retriever, through TestClient."""

import re
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

from entrypoints.entrypoint_fakes import REPO_ROOT, FakeRetriever
from masdar.app.answer import AnswerService
from masdar.app.search import SearchService
from masdar.config import Settings
from masdar.domain.search import MAX_QUERY_CHARS
from masdar.entrypoints import api
from masdar.entrypoints.api import create_app
from masdar.entrypoints.security import RateLimiter


@pytest.fixture
def client(service: SearchService, settings: Settings) -> Iterator[TestClient]:
    # `with` runs the lifespan, which is where the service is installed.
    with TestClient(create_app(service, settings)) as test_client:
        yield test_client


def search(client: TestClient, **params: Any) -> Any:
    response = client.get("/api/search", params=params)
    assert response.status_code == 200, response.text
    return response.json()


class TestSearch:
    def test_returns_cited_articles_with_status_and_provenance(self, client: TestClient) -> None:
        body = search(client, q="  كم مدة إجازة الأمومة؟ ")
        assert (body["query"], body["k"], body["pipeline"]) == ("كم مدة إجازة الأمومة؟", 5, "fake")
        first = body["results"][0]
        assert first["rank"] == 1
        assert first["article_id"] == "labor-law:151"
        assert first["citation"] == "نظام العمل — المادة الحادية والخمسون بعد المائة"
        assert first["article_title"] == "إجازة الوضع"
        assert (first["part"], first["chapter"]) == ("الباب التاسع", "الفصل الثاني")
        assert (first["status"], first["status_label"]) == ("amended", "معدّل")
        # The latest decree wins, not the last one listed.
        assert first["latest_amendment"] == {
            "kind": "replace",
            "decree": "م/44",
            "issued": "1446/02/08",
            "effective": None,
        }
        assert first["source_url"].startswith("https://laws.boe.gov.sa/BoeLaws/Laws/LawDetails/")
        assert first["matched_text"] == first["text"]

    def test_status_labels_cover_every_current_status(self, client: TestClient) -> None:
        labels = {hit["status"]: hit["status_label"] for hit in search(client, q="x")["results"]}
        assert labels == {"amended": "معدّل", "review_needed": "يحتاج مراجعة", "in_force": "ساري"}

    def test_article_without_amendments_has_no_provenance(self, client: TestClient) -> None:
        results = search(client, q="الشركات", law="companies-law")["results"]
        assert [hit["latest_amendment"] for hit in results] == [None]

    def test_k_limits_the_results(self, client: TestClient) -> None:
        assert len(search(client, q="سؤال", k=1)["results"]) == 1

    def test_law_filter_is_passed_through(self, client: TestClient) -> None:
        body = search(client, q="سؤال", law=["pdpl", "companies-law", "pdpl"])
        assert body["laws"] == ["pdpl", "companies-law"]
        assert {hit["law_id"] for hit in body["results"]} == {"pdpl", "companies-law"}

    def test_the_service_receives_the_trimmed_question(
        self, client: TestClient, retriever: FakeRetriever
    ) -> None:
        search(client, q="  مكافأة نهاية الخدمة  ")
        assert retriever.queries == ["مكافأة نهاية الخدمة"]


class TestValidation:
    @pytest.mark.parametrize("query", ["   ", "س" * (MAX_QUERY_CHARS + 1)])
    def test_invalid_question_is_422_in_both_languages(
        self, client: TestClient, query: str
    ) -> None:
        response = client.get("/api/search", params={"q": query})
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "invalid_query"
        assert error["message"]
        assert "السؤال" in error["message_ar"]

    @pytest.mark.parametrize("k", [0, 21, -1])
    def test_k_out_of_bounds_is_422(self, client: TestClient, k: int) -> None:
        response = client.get("/api/search", params={"q": "سؤال", "k": k})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    @pytest.mark.parametrize("k", [1, 20])
    def test_k_bounds_are_inclusive(self, client: TestClient, k: int) -> None:
        assert client.get("/api/search", params={"q": "سؤال", "k": k}).status_code == 200

    def test_missing_question_is_422(self, client: TestClient) -> None:
        error = client.get("/api/search").json()["error"]
        assert error["code"] == "invalid_request"
        assert "q" in error["message"]

    def test_unknown_law_is_422(self, client: TestClient) -> None:
        response = client.get("/api/search", params={"q": "سؤال", "law": "tax-law"})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "unknown_law"

    def test_unexpected_errors_never_leak_a_traceback(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = SearchService(FakeRetriever())

        def explode(*_: object, **__: object) -> list[object]:
            raise RuntimeError("secret internal detail")

        monkeypatch.setattr(broken, "search", explode)
        with TestClient(create_app(broken, settings), raise_server_exceptions=False) as client:
            response = client.get("/api/search", params={"q": "سؤال"})
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert "secret" not in response.text
        assert "Traceback" not in response.text


class TestMeta:
    def test_health(self, client: TestClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "pipeline": "fake",
            "answers": False,
            "version": "0.1.0",
        }

    def test_laws_come_from_the_dataset_stats(self, client: TestClient) -> None:
        laws = client.get("/api/laws").json()
        assert [law["law_id"] for law in laws] == ["labor-law", "pdpl", "companies-law"]
        assert laws[0]["title"] == "نظام العمل"
        assert laws[0]["current"] == 211
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", laws[0]["retrieved_on"])
        assert laws[0]["source_url"].startswith("https://laws.boe.gov.sa/")

    def test_openapi_docs_are_served(self, client: TestClient) -> None:
        assert client.get("/docs").status_code == 200
        assert "/api/search" in client.get("/openapi.json").json()["paths"]


class TestWebUi:
    def test_index_is_served_at_root(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert 'dir="rtl"' in response.text

    @pytest.mark.parametrize("asset", ["app.js", "styles.css", "favicon.svg"])
    def test_assets_are_served(self, client: TestClient, asset: str) -> None:
        assert client.get(f"/{asset}").status_code == 200

    def test_unknown_path_is_404(self, client: TestClient) -> None:
        assert client.get("/nope.txt").status_code == 404


class TestSecurityHeaders:
    @pytest.mark.parametrize("path", ["/", "/api/health", "/api/search?q=x", "/nope"])
    def test_every_response_is_hardened(self, client: TestClient, path: str) -> None:
        headers = client.get(path).headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        csp = headers["Content-Security-Policy"]
        assert "script-src 'self';" in csp
        assert "unsafe-inline" not in csp
        assert "frame-ancestors 'self' https://huggingface.co" in csp

    def test_only_the_docs_page_relaxes_the_policy(self, client: TestClient) -> None:
        csp = client.get("/docs").headers["Content-Security-Policy"]
        assert "https://cdn.jsdelivr.net" in csp


class TestErrors:
    def test_unknown_api_path_is_a_json_404(self, client: TestClient) -> None:
        response = client.get("/api/nope")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_a_crash_is_a_generic_500_that_keeps_the_security_headers(
        self, settings: Settings
    ) -> None:
        class Exploding:
            name = "boom"

            def search(self, query: str, k: int) -> list[Any]:  # noqa: ARG002
                raise RuntimeError("secret detail")

        app = create_app(SearchService(Exploding()), settings)
        with TestClient(app, raise_server_exceptions=False) as crashing:
            response = crashing.get("/api/search", params={"q": "س"})
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert "secret detail" not in response.text
        assert response.headers["X-Content-Type-Options"] == "nosniff"


class TestRateLimit:
    def make_client(self, service: SearchService, settings: Settings) -> TestClient:
        return TestClient(create_app(service, settings, rate_limiter=RateLimiter(limit=2)))

    def test_over_the_limit_is_429_with_retry_after(
        self, service: SearchService, settings: Settings
    ) -> None:
        with self.make_client(service, settings) as client:
            codes = [client.get("/api/search", params={"q": "س"}).status_code for _ in range(3)]
            response = client.get("/api/laws")
        assert codes == [200, 200, 429]
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "rate_limited"
        assert int(response.headers["Retry-After"]) >= 1
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    def test_health_and_static_files_are_not_limited(
        self, service: SearchService, settings: Settings
    ) -> None:
        with self.make_client(service, settings) as client:
            codes = {client.get(path).status_code for path in ["/api/health", "/"] * 5}
        assert codes == {200}


class TestDefaultService:
    def test_builds_the_service_from_the_container_at_startup(
        self,
        service: SearchService,
        settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[Settings] = []

        def factory(given: Settings) -> SearchService:
            calls.append(given)
            return service

        monkeypatch.setattr(api, "default_search_service", factory)
        with TestClient(create_app(settings=settings)) as client:
            client.get("/api/health")
            client.get("/api/health")
        assert calls == [settings]  # once per process, not per request


class TestClientKey:
    def make_client(self, service: SearchService, hops: int) -> TestClient:
        settings = Settings(dataset_dir=REPO_ROOT / "data" / "dataset", trusted_proxy_hops=hops)
        return TestClient(create_app(service, settings, rate_limiter=RateLimiter(limit=2)))

    def test_forged_forwarded_for_gets_no_fresh_bucket(self, service: SearchService) -> None:
        # The edge proxy appends the real address; the client controls the rest.
        with self.make_client(service, hops=1) as client:
            codes = [
                client.get(
                    "/api/laws", headers={"X-Forwarded-For": f"10.0.0.{n}, 203.0.113.7"}
                ).status_code
                for n in range(3)
            ]
        assert codes == [200, 200, 429]

    def test_distinct_real_clients_have_separate_buckets(self, service: SearchService) -> None:
        with self.make_client(service, hops=1) as client:
            codes = [
                client.get("/api/laws", headers={"X-Forwarded-For": f"203.0.113.{n}"}).status_code
                for n in range(3)
            ]
        assert codes == [200, 200, 200]

    def test_without_trusted_proxies_the_header_is_ignored(self, service: SearchService) -> None:
        with self.make_client(service, hops=0) as client:
            codes = [
                client.get("/api/laws", headers={"X-Forwarded-For": f"203.0.113.{n}"}).status_code
                for n in range(3)
            ]
        assert codes == [200, 200, 429]


class ConstantScorer:
    """Scores every (question, sentence) pair the same; enough to drive the flow."""

    def __init__(self, value: float) -> None:
        self.value = value

    def score(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        return [self.value] * len(pairs)


class TestAnswer:
    def make_client(self, service: SearchService, settings: Settings, score: float) -> TestClient:
        answers = AnswerService(service, ConstantScorer(score), threshold=0.0)
        return TestClient(create_app(service, settings, answers=answers))

    def test_quotes_the_law_verbatim_with_its_citation(
        self, service: SearchService, settings: Settings
    ) -> None:
        with self.make_client(service, settings, score=5.0) as client:
            assert client.get("/api/health").json()["answers"] is True
            body = client.get("/api/answer", params={"q": "كم مدة إجازة الوضع؟"}).json()
        assert body["status"] == "answered"
        quote = body["quotes"][0]
        top = body["results"][0]
        assert quote["article_id"] == top["article_id"]
        assert quote["sentence"] in top["text"]
        assert quote["citation"] == top["citation"]
        assert quote["source_url"].startswith("https://laws.boe.gov.sa/")

    def test_low_confidence_is_an_explicit_refusal_with_related_articles(
        self, service: SearchService, settings: Settings
    ) -> None:
        with self.make_client(service, settings, score=-50.0) as client:
            body = client.get("/api/answer", params={"q": "ما عاصمة فرنسا؟", "k": 2}).json()
        assert (body["status"], body["quotes"]) == ("not_found", [])
        assert len(body["results"]) == 2

    def test_search_only_deployments_say_so(self, client: TestClient) -> None:
        response = client.get("/api/answer", params={"q": "س"})
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "answers_unavailable"


class TestCheck:
    CONTRACT = (
        "المادة الأولى: يخضع الموظف لفترة تجربة مدتها مائتا يوم.\n"
        "المادة الثانية: يستحق الموظف إجازة سنوية مدتها ثلاثون يوماً.\n"
        "المادة الثالثة: يلتزم الموظف بالمحافظة على سرية المعلومات."
    )

    def test_verdicts_per_clause_with_citations(self, client: TestClient) -> None:
        response = client.post("/api/check", json={"text": self.CONTRACT})
        assert response.status_code == 200, response.text
        body = response.json()
        assert [len(clause["findings"]) for clause in body["clauses"]] == [1, 1, 0]
        violation = body["clauses"][0]["findings"][0]
        assert (violation["kind"], violation["article_id"]) == ("violation", "labor-law:53")
        assert violation["source_url"].startswith("https://laws.boe.gov.sa/")
        assert body["clauses"][1]["findings"][0]["kind"] == "compliant"
        assert body["counts"] == {"violation": 1, "compliant": 1, "review_needed": 0}
        assert all(clause["related"] for clause in body["clauses"])

    @pytest.mark.parametrize(
        ("payload", "code"),
        [
            pytest.param({"text": "   "}, "invalid_document", id="blank"),
            pytest.param({"text": "س" * 20_001}, "invalid_request", id="too-long"),
            pytest.param({}, "invalid_request", id="missing"),
        ],
    )
    def test_bad_documents_are_422(self, client: TestClient, payload: Any, code: str) -> None:
        response = client.post("/api/check", json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == code


class TestRequestLimits:
    def test_a_huge_body_is_refused_before_it_is_read(self, client: TestClient) -> None:
        response = client.post(
            "/api/check",
            content=b'{"text": "' + b"a" * (api.MAX_BODY_BYTES + 1) + b'"}',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "body_too_large"
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    def test_a_body_of_unknown_size_is_refused(self, client: TestClient) -> None:
        def chunks() -> Iterator[bytes]:
            yield b'{"text": "x"}'

        response = client.post(
            "/api/check", content=chunks(), headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 411

    def test_checks_have_their_own_stricter_limit(
        self, service: SearchService, settings: Settings
    ) -> None:
        app = create_app(service, settings, check_limiter=RateLimiter(limit=1))
        with TestClient(app) as client:
            first = client.post("/api/check", json={"text": TestCheck.CONTRACT})
            second = client.post("/api/check", json={"text": TestCheck.CONTRACT})
            search = client.get("/api/search", params={"q": "س"})
        assert (first.status_code, second.status_code, search.status_code) == (200, 429, 200)
