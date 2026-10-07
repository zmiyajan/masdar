"""A tiny three-law corpus and a recording retriever for entrypoint tests."""

from pathlib import Path

from masdar.domain.amendments import Amendment, AmendmentKind, ArticleStatus, HijriDate
from masdar.domain.models import Article, Chunk, Hit
from masdar.domain.ordinals import ArticleNumber

REPO_ROOT = Path(__file__).resolve().parents[3]

MATERNITY = Article(
    "labor-law",
    "نظام العمل",
    ArticleNumber(151),
    "المادة الحادية والخمسون بعد المائة",
    "للمرأة العاملة الحق في إجازة وضع بأجر كامل لمدة عشرة أسابيع.",
    ArticleStatus.AMENDED,
    title="إجازة الوضع",
    part="الباب التاسع",
    chapter="الفصل الثاني",
    original_text="للمرأة العاملة الحق في إجازة وضع لمدة الأسابيع الأربعة السابقة.",
    amendments=(
        # Listed newest first on purpose: "latest" must mean by date, not position.
        Amendment(AmendmentKind.REPLACE, "عدلت ...", "م/44", HijriDate(1446, 2, 8), None, "y"),
        Amendment(AmendmentKind.REPLACE, "عدلت ...", "م/5", HijriDate(1434, 3, 23), None, "x"),
    ),
)
TRANSFER = Article(
    "pdpl",
    "نظام حماية البيانات الشخصية",
    ArticleNumber(29),
    "المادة التاسعة والعشرون",
    "يجوز للجهة المتحكمة نقل البيانات الشخصية إلى خارج المملكة.",
    ArticleStatus.REVIEW_NEEDED,
    amendments=(Amendment(AmendmentKind.PARTIAL, "عدلت الفقرة ...", "م/148"),),
)
FORMS = Article(
    "companies-law",
    "نظام الشركات",
    ArticleNumber(3),
    "المادة الثالثة",
    "تتخذ الشركة أحد الأشكال الآتية: شركة التضامن، شركة التوصية البسيطة.",
)
ARTICLES = (MATERNITY, TRANSFER, FORMS)
SOURCE_URLS = {
    "labor-law": "https://laws.boe.gov.sa/labor",
    "pdpl": "https://laws.boe.gov.sa/pdpl",
    "companies-law": "https://laws.boe.gov.sa/companies",
}


class FakeRetriever:
    """Returns every article in a fixed order and records each query."""

    name = "fake"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, k: int) -> list[Hit]:
        self.queries.append(query)
        chunks = [Chunk(f"{a.article_id}#0", a, a.text, a.text) for a in ARTICLES]
        return [
            Hit(chunk, score=1.0 / rank, rank=rank, retriever=self.name)
            for rank, chunk in enumerate(chunks[:k], start=1)
        ]
