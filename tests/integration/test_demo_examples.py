"""The example questions on the web page behave as the page promises.

The chips are the first thing a visitor clicks, so they are pinned against
the real models: the law questions are answered with a quote from the expected
law, and the traffic question is refused (it shows abstention on purpose).
"""

import re
from pathlib import Path

import pytest

from masdar.app.answer import AnswerService
from masdar.config import Settings
from masdar.container import answer_service, default_search_service
from masdar.domain.answer import AnswerStatus
from masdar.entrypoints.api import WEB_DIR

EXPECTED_LAW = {
    "كم الإجازة السنوية للعامل؟": "labor-law",
    "هل يجوز نقل بيانات العملاء خارج المملكة؟": "pdpl",
    "كم ساعات العمل في اليوم؟": "labor-law",
    "ما أشكال الشركات في النظام؟": "companies-law",
    "كم غرامة قطع الإشارة؟": None,  # outside the three laws: must be refused
}

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def answers(snapshot_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> AnswerService:
    settings = Settings(snapshot_dir=snapshot_dir, index_dir=tmp_path_factory.mktemp("index"))
    service = answer_service(default_search_service(settings))
    assert service is not None
    return service


def test_every_chip_is_pinned() -> None:
    index = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert re.findall(r'data-question="([^"]+)"', index) == list(EXPECTED_LAW)


@pytest.mark.parametrize(("question", "law"), EXPECTED_LAW.items())
def test_chip_outcome(answers: AnswerService, question: str, law: str | None) -> None:
    answer = answers.answer(question)
    if law is None:
        assert answer.status is AnswerStatus.NOT_FOUND
    else:
        assert answer.top is not None
        assert answer.top.article.law_id == law
