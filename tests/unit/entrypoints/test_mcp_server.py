"""MCP tools, called directly and through the server, with a fake retriever."""

import asyncio
from collections.abc import Sequence

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from entrypoints.entrypoint_fakes import ARTICLES, SOURCE_URLS, FakeRetriever
from masdar.app.answer import AnswerService
from masdar.app.search import SearchService
from masdar.domain.compliance import FindingKind
from masdar.entrypoints.mcp_server import RegulationTools, build_server


@pytest.fixture
def tools(service: SearchService) -> RegulationTools:
    return RegulationTools(service, ARTICLES, SOURCE_URLS)


class TestSearchRegulations:
    def test_returns_cited_articles_with_status(self, tools: RegulationTools) -> None:
        response = tools.search_regulations("  إجازة الأمومة ", k=2)
        assert (response.query, response.k, response.pipeline) == ("إجازة الأمومة", 2, "fake")
        assert [hit.article_id for hit in response.results] == ["labor-law:151", "pdpl:29"]
        first = response.results[0]
        assert first.citation == "نظام العمل — المادة الحادية والخمسون بعد المائة"
        assert first.status_label == "معدّل"
        assert first.source_url == SOURCE_URLS["labor-law"]

    def test_law_filter(self, tools: RegulationTools, retriever: FakeRetriever) -> None:
        response = tools.search_regulations("نقل البيانات", law="pdpl")
        assert response.laws == ["pdpl"]
        assert [hit.law_id for hit in response.results] == ["pdpl"]
        assert retriever.queries == ["نقل البيانات"]

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            pytest.param({"query": " "}, "empty", id="blank-query"),
            pytest.param({"query": "سؤال", "k": 0}, "between 1 and 20", id="k-too-small"),
            pytest.param({"query": "سؤال", "k": 21}, "between 1 and 20", id="k-too-large"),
            pytest.param({"query": "سؤال", "law": "tax"}, "Unknown law", id="unknown-law"),
        ],
    )
    def test_bad_input_is_a_tool_error(
        self, tools: RegulationTools, kwargs: dict[str, object], message: str
    ) -> None:
        with pytest.raises(ToolError, match=message):
            tools.search_regulations(**kwargs)  # type: ignore[arg-type]


class TestGetArticle:
    def test_full_text_and_amendment_history(self, tools: RegulationTools) -> None:
        detail = tools.get_article(" labor-law:151 ")
        assert detail.text.startswith("للمرأة العاملة")
        assert detail.original_text is not None
        assert [(a.decree, a.issued) for a in detail.amendments] == [
            ("م/44", "1446/02/08"),
            ("م/5", "1434/03/23"),
        ]
        assert detail.amendments[0].note == "عدلت ..."
        assert detail.status_label == "معدّل"

    def test_undated_partial_amendment(self, tools: RegulationTools) -> None:
        detail = tools.get_article("pdpl:29")
        assert detail.status_label == "يحتاج مراجعة"
        assert [(a.kind, a.issued) for a in detail.amendments] == [("partial", None)]

    def test_unknown_article_is_a_tool_error(self, tools: RegulationTools) -> None:
        with pytest.raises(ToolError, match="labor-law:9999"):
            tools.get_article("labor-law:9999")


class TestServer:
    def test_registers_both_read_only_tools(self, service: SearchService) -> None:
        server = build_server(service, ARTICLES, SOURCE_URLS)
        tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
        assert set(tools) == {"search_regulations", "get_article", "check_contract"}
        search = tools["search_regulations"]
        assert set(search.input_schema["properties"]) == {"query", "k", "law"}
        assert search.input_schema["required"] == ["query"]
        assert search.annotations is not None
        assert search.annotations.read_only_hint is True

    def test_tool_call_round_trip(self, service: SearchService) -> None:
        server = build_server(service, ARTICLES, SOURCE_URLS)
        result = asyncio.run(server.call_tool("get_article", {"article_id": "companies-law:3"}))
        structured = getattr(result, "structured_content", None)
        assert structured is not None
        assert structured["citation"] == "نظام الشركات — المادة الثالثة"
        assert structured["status_label"] == "ساري"


class _ConfidentScorer:
    def score(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        return [5.0] * len(pairs)


class TestAnswerQuestion:
    def test_quotes_verbatim_and_is_registered_only_when_available(
        self, service: SearchService
    ) -> None:
        answers = AnswerService(service, _ConfidentScorer(), threshold=0.0)
        tools = RegulationTools(service, ARTICLES, SOURCE_URLS, answers)
        response = tools.answer_question("كم مدة إجازة الوضع؟")
        assert response.status == "answered"
        assert response.quotes[0].sentence in response.results[0].text
        with_answers = asyncio.run(
            build_server(service, ARTICLES, SOURCE_URLS, answers).list_tools()
        )
        without = asyncio.run(build_server(service, ARTICLES, SOURCE_URLS).list_tools())
        assert "answer_question" in {tool.name for tool in with_answers}
        assert "answer_question" not in {tool.name for tool in without}

    def test_unavailable_or_unknown_law_is_a_tool_error(self, tools: RegulationTools) -> None:
        with pytest.raises(ToolError, match="not available"):
            tools.answer_question("سؤال")


class TestCheckContract:
    def test_cites_the_article_for_a_violation(self, tools: RegulationTools) -> None:
        response = tools.check_contract("يخضع الموظف لفترة تجربة مدتها مائتا يوم.")
        [finding] = response.clauses[0].findings
        assert (finding.rule_id, finding.kind, finding.article_id) == (
            "probation-max",
            "violation",
            "labor-law:53",
        )
        assert finding.kind_label == "مخالفة"
        assert response.counts[FindingKind.VIOLATION] == 1

    def test_empty_text_is_a_tool_error(self, tools: RegulationTools) -> None:
        with pytest.raises(ToolError, match="empty"):
            tools.check_contract("   ")
