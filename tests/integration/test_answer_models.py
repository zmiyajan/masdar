"""Extractive answers with the real default models (slow; needs the ``ml`` extra).

Run with ``make test-slow``. They guard what fakes cannot: that the calibrated
threshold still separates known answers from out-of-scope questions with the
pinned cross-encoder, and that quotes are verbatim sentences of the right article.
"""

from pathlib import Path

import pytest

from masdar.adapters.cross_encoder import (
    DEFAULT_ANSWER_THRESHOLD,
    DEFAULT_RERANK_CANDIDATES,
    CrossEncoderReranker,
)
from masdar.adapters.dense import DenseRetriever
from masdar.app.answer import AnswerService
from masdar.app.search import SearchService
from masdar.config import Settings
from masdar.container import load_current_corpus
from masdar.domain.answer import AnswerStatus

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def service(snapshot_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> AnswerService:
    pytest.importorskip("sentence_transformers")
    corpus = load_current_corpus(Settings(snapshot_dir=snapshot_dir))
    dense = DenseRetriever.from_chunks(corpus.chunks, cache_dir=tmp_path_factory.mktemp("index"))
    reranker = CrossEncoderReranker.from_model()
    search = SearchService(dense, reranker, candidates=DEFAULT_RERANK_CANDIDATES)
    return AnswerService(search, reranker.scorer, threshold=DEFAULT_ANSWER_THRESHOLD)


@pytest.mark.parametrize(
    ("question", "article_id", "expected_words"),
    [
        pytest.param(
            "كم مدة إجازة الوضع للمرأة العاملة؟", "labor-law:151", "أسبوعاً", id="maternity"
        ),
        pytest.param(
            "ما المدة القصوى لفترة التجربة في عقد العمل؟",
            "labor-law:53",
            "مائة وثمانين",
            id="probation",
        ),
        pytest.param(
            "ما مدة الإشعار المطلوبة من صاحب العمل لإنهاء العقد غير محدد المدة؟",
            "labor-law:75",
            "إشعار",
            id="notice-period",
        ),
    ],
)
def test_answers_with_a_verbatim_sentence_of_the_right_article(
    service: AnswerService, question: str, article_id: str, expected_words: str
) -> None:
    answer = service.answer(question)
    assert answer.status is AnswerStatus.ANSWERED
    assert answer.top is not None
    assert answer.top.article.article_id == article_id
    assert expected_words in answer.top.sentence
    assert all(e.sentence in e.article.text for e in answer.evidence)


@pytest.mark.parametrize(
    "question",
    [
        pytest.param("ما عاصمة المملكة العربية السعودية؟", id="general-knowledge"),
        pytest.param("كم نسبة ضريبة القيمة المضافة في المملكة؟", id="vat"),
    ],
)
def test_refuses_what_the_corpus_does_not_answer(service: AnswerService, question: str) -> None:
    answer = service.answer(question)
    assert answer.status is AnswerStatus.NOT_FOUND
    assert answer.related, "related articles are still returned"
