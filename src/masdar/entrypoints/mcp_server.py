"""MCP server: Saudi regulations as tools for AI agents (``masdar-mcp``, stdio).

Agents get the same `SearchService` and the same citation shape as the web
API, so an assistant quoting Masdar cites exactly what a person would see.
Built with the official SDK's ``MCPServer`` (mcp 2.x; formerly ``FastMCP``).
"""

from collections.abc import Iterable, Mapping

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from masdar.app.search import SearchService
from masdar.config import Settings
from masdar.container import default_search_service, load_current_corpus
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.models import Article
from masdar.entrypoints.laws import load_law_summaries
from masdar.entrypoints.schemas import ArticleDetail, SearchResponse, to_detail, to_hit

MAX_K = 20

_INSTRUCTIONS = (
    "Search Saudi regulations (Labor Law, PDPL, Companies Law) in Arabic. "
    "Always cite the returned `citation` and `source_url`, and warn the user when an "
    "article's status is `review_needed`. Results are retrieval, not legal advice."
)
_READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)


class RegulationTools:
    """The MCP tools, as plain methods so they can be tested without a transport."""

    def __init__(
        self,
        service: SearchService,
        articles: Iterable[Article],
        source_urls: Mapping[str, str],
    ) -> None:
        """Create the tools.

        Args:
            service: The search pipeline.
            articles: Every current article, for lookups by id.
            source_urls: Official page per law id; its keys are the valid laws.
        """
        self._service = service
        self._articles = {article.article_id: article for article in articles}
        self._source_urls = dict(source_urls)

    def search_regulations(self, query: str, k: int = 5, law: str | None = None) -> SearchResponse:
        """Find the articles of Saudi law that answer a question, with citations.

        Args:
            query: The question, ideally in Arabic (e.g. "كم مدة إجازة الأمومة؟").
            k: How many articles to return, 1 to 20.
            law: Optional law id to search within: labor-law, pdpl or companies-law.

        Returns:
            Ranked articles with citation, status (in force, amended, or review
            needed), latest amendment and official source link.
        """
        if not 1 <= k <= MAX_K:
            raise ToolError(f"k must be between 1 and {MAX_K}")
        if law is not None and law not in self._source_urls:
            raise ToolError(f"Unknown law {law!r}; use one of {sorted(self._source_urls)}")
        laws = [law] if law else []
        try:
            results = self._service.search(query, k=k, laws=laws or None)
        except InvalidDomainObjectError as error:
            raise ToolError(str(error)) from error
        return SearchResponse(
            query=query.strip(),
            k=k,
            laws=laws,
            pipeline=self._service.name,
            results=[to_hit(result, self._source_urls) for result in results],
        )

    def get_article(self, article_id: str) -> ArticleDetail:
        """Return one article's full text in force and its amendment history.

        Args:
            article_id: An id from search results, e.g. "labor-law:151".

        Returns:
            The article with its original wording and every amendment note.
        """
        article = self._articles.get(article_id.strip())
        if article is None:
            raise ToolError(f"No current article with id {article_id!r}")
        return to_detail(article, self._source_urls)


def build_server(
    service: SearchService,
    articles: Iterable[Article],
    source_urls: Mapping[str, str],
) -> MCPServer:
    """Wire the tools into an MCP server.

    Args:
        service: The search pipeline.
        articles: Every current article, for `get_article`.
        source_urls: Official page per law id.
    """
    tools = RegulationTools(service, articles, source_urls)
    server: MCPServer = MCPServer(name="masdar", instructions=_INSTRUCTIONS)
    server.add_tool(tools.search_regulations, annotations=_READ_ONLY)
    server.add_tool(tools.get_article, annotations=_READ_ONLY)
    return server


def main() -> None:  # pragma: no cover - wiring only; build_server is tested
    """Serve over stdio, the transport desktop agents launch servers with."""
    settings = Settings()
    laws = load_law_summaries(settings.dataset_dir / "stats.json")
    corpus = load_current_corpus(settings)
    build_server(
        default_search_service(settings),
        corpus.articles,
        {law.law_id: law.source_url for law in laws},
    ).run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
