"""Tests for extractive answers: sentence splitting, invariants, the service, the report."""

import json
import re
from collections.abc import Sequence
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from masdar.adapters.out_of_scope_jsonl import JsonlOutOfScopeSource
from masdar.app.answer import AnswerService, measure_answers
from masdar.app.search import SearchService
from masdar.domain.answer import (
    MIN_UNIT_WORDS,
    Answer,
    AnswerQualityReport,
    AnswerStatus,
    Evidence,
    OutOfScopeQuestion,
    split_sentences,
    summarize_answers,
    top_evidence_grade,
)
from masdar.domain.errors import InvalidDomainObjectError, SourceFormatError
from masdar.domain.gold import GoldQuery, QueryStyle
from masdar.domain.models import Article, Chunk, Hit
from masdar.domain.ordinals import ArticleNumber

REPO_ROOT = Path(__file__).resolve().parents[2]

PROBATION = (
    "إذا كان العامل خاضعاً للتجربة، وجب النص على ذلك صراحة في عقد العمل. "
    "ولا يزيد مجموع المدة على (مائة وثمانين) يوماً. ولكل من الطرفين الحق في إنهاء العقد"
)
NOTICE = (
    "1- إذا كان العقد غير محدد المدة، جاز لأي من طرفيه إنهاؤه، وفق ما يلي:\n"
    "أ- إذا كان الإنهاء من طرف العامل، فيجب عليه إشعار صاحب العمل قبل (ثلاثين) يوماً.\n"
    "ب- إذا كان الإنهاء من طرف صاحب العمل، فيجب عليه إشعار العامل قبل (ستين) يوماً."
)


def article(number: int, text: str, law: str = "labor-law") -> Article:
    return Article(law, "نظام العمل", ArticleNumber(number), f"المادة {number}", text)


def words(text: str) -> list[str]:
    return text.split()


# ----------------------------------------------------------------- split_sentences


class TestSplitSentences:
    def test_splits_on_full_stops(self) -> None:
        assert split_sentences(PROBATION) == [
            "إذا كان العامل خاضعاً للتجربة، وجب النص على ذلك صراحة في عقد العمل.",
            "ولا يزيد مجموع المدة على (مائة وثمانين) يوماً.",
            "ولكل من الطرفين الحق في إنهاء العقد",
        ]

    def test_numbered_paragraphs_are_units(self) -> None:
        units = split_sentences(NOTICE)
        assert len(units) == 3
        assert units[1].startswith("أ- ")
        assert units[2].startswith("ب- ")

    def test_arabic_semicolon_ends_a_unit(self) -> None:
        text = "يعاقب المخالف بغرامة لا تقل عن ألف ريال؛ وتضاعف الغرامة عند تكرار المخالفة"
        assert split_sentences(text) == [
            "يعاقب المخالف بغرامة لا تقل عن ألف ريال؛",
            "وتضاعف الغرامة عند تكرار المخالفة",
        ]

    def test_colon_inside_a_line_does_not_split(self) -> None:
        text = "ومن ذلك: الاسم، ورقم الهوية الشخصية، والعناوين، وأرقام التواصل."
        assert split_sentences(text) == [text]

    def test_decimal_point_does_not_split(self) -> None:
        text = "يستحق العامل زيادة قدرها 1.5 من الأجر عن كل ساعة إضافية."
        assert split_sentences(text) == [text]

    def test_short_unit_merges_into_the_next(self) -> None:
        text = "أ-\nيستحق العامل إجازة سنوية بأجر كامل."
        assert split_sentences(text) == [text]

    def test_short_last_unit_merges_into_the_previous(self) -> None:
        text = "يستحق العامل إجازة سنوية بأجر كامل.\nوفق ما يلي:"
        assert split_sentences(text) == [text]

    def test_a_short_text_is_one_unit(self) -> None:
        assert split_sentences("  يسمى النظام.  ") == ["يسمى النظام."]

    @pytest.mark.parametrize("text", ["", "   ", "\n\n"])
    def test_blank_text_has_no_units(self, text: str) -> None:
        assert split_sentences(text) == []

    @given(
        st.lists(
            st.text(alphabet="ابتثجح لمن.؛;:-\n123", min_size=0, max_size=40),
            max_size=8,
        ).map("".join)
    )
    def test_units_are_verbatim_and_cover_the_text(self, text: str) -> None:
        units = split_sentences(text)
        assert all(unit and unit in text for unit in units)
        assert re.sub(r"\s", "", "".join(units)) == re.sub(r"\s", "", text)

    @given(st.lists(st.sampled_from(["العامل", "يستحق", "أجر", "1-", "أ-"]), max_size=30))
    def test_no_tiny_units_when_there_is_enough_text(self, tokens: list[str]) -> None:
        text = ". ".join(" ".join(tokens[i : i + 2]) for i in range(0, len(tokens), 2))
        units = split_sentences(text)
        if len(words(text)) >= MIN_UNIT_WORDS:
            assert all(len(words(unit)) >= MIN_UNIT_WORDS for unit in units)


# ------------------------------------------------------------------- invariants


class TestEvidenceAndAnswer:
    def test_evidence_must_quote_the_article(self) -> None:
        source = article(53, PROBATION)
        assert Evidence(source, "ولكل من الطرفين الحق في إنهاء العقد", 1.0).score == 1.0
        with pytest.raises(InvalidDomainObjectError, match="verbatim"):
            Evidence(source, "للعامل الحق في إجازة مدفوعة", 1.0)

    @pytest.mark.parametrize("sentence", ["", "   "])
    def test_evidence_rejects_blank_quotes(self, sentence: str) -> None:
        with pytest.raises(InvalidDomainObjectError):
            Evidence(article(53, PROBATION), sentence, 1.0)

    def test_evidence_rejects_non_finite_scores(self) -> None:
        with pytest.raises(InvalidDomainObjectError, match="finite"):
            Evidence(article(53, PROBATION), "ولكل من الطرفين", float("nan"))

    def test_answered_needs_evidence(self) -> None:
        with pytest.raises(InvalidDomainObjectError):
            Answer("سؤال", AnswerStatus.ANSWERED, ())

    def test_not_found_has_no_evidence(self) -> None:
        evidence = Evidence(article(53, PROBATION), "ولكل من الطرفين", 1.0)
        with pytest.raises(InvalidDomainObjectError):
            Answer("سؤال", AnswerStatus.NOT_FOUND, (evidence,))
        assert Answer("سؤال", AnswerStatus.NOT_FOUND, ()).top is None

    def test_out_of_scope_question_needs_text(self) -> None:
        with pytest.raises(InvalidDomainObjectError):
            OutOfScopeQuestion("oos-1", " ", "t", QueryStyle.FORMAL)


# ---------------------------------------------------------------------- service


class FakeRetriever:
    """Returns one chunk per article, in the given order."""

    def __init__(self, articles: Sequence[Article], scores: Sequence[float]) -> None:
        self._hits = [
            Hit(Chunk(f"{a.article_id}#0", a, a.text, a.text), score, rank, "fake")
            for rank, (a, score) in enumerate(zip(articles, scores, strict=True), start=1)
        ]

    @property
    def name(self) -> str:
        return "fake"

    def search(self, query: str, k: int) -> list[Hit]:  # noqa: ARG002 - port signature
        return self._hits[:k]


class KeywordScorer:
    """Scores a pair by the keywords of the question found in the passage."""

    def __init__(self, keywords: dict[str, float]) -> None:
        self._keywords = keywords
        self.calls: list[list[tuple[str, str]]] = []

    def score(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        self.calls.append(list(pairs))
        return [
            sum(weight for word, weight in self._keywords.items() if word in passage) - 1.0
            for _, passage in pairs
        ]


class ShortScorer:
    def score(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        return [0.0] * (len(pairs) - 1)


def service(
    scorer: KeywordScorer | ShortScorer,
    *,
    article_scores: Sequence[float] = (0.0, 0.0),
    threshold: float = 0.0,
    max_sentences: int = 2,
) -> AnswerService:
    articles = [article(53, PROBATION), article(75, NOTICE)]
    search = SearchService(FakeRetriever(articles, article_scores))
    return AnswerService(search, scorer, threshold=threshold, max_sentences=max_sentences)


class TestAnswerService:
    def test_quotes_the_best_sentence_verbatim_with_its_article(self) -> None:
        answer = service(KeywordScorer({"ستين": 5.0})).answer("كم مدة إشعار صاحب العمل؟")
        assert answer.status is AnswerStatus.ANSWERED
        assert answer.top is not None
        assert answer.top.article.article_id == "labor-law:75"
        assert answer.top.sentence.startswith("ب- ")
        assert answer.top.sentence in answer.top.article.text
        assert [r.article.article_id for r in answer.related] == ["labor-law:53", "labor-law:75"]

    def test_refuses_below_the_threshold_but_returns_related(self) -> None:
        answer = service(KeywordScorer({}), threshold=0.0).answer("ما عاصمة المملكة؟")
        assert answer.status is AnswerStatus.NOT_FOUND
        assert answer.evidence == ()
        assert len(answer.related) == 2

    def test_article_score_is_added_to_the_sentence_score(self) -> None:
        # Same sentence score everywhere; the reranker prefers the second article.
        answer = service(
            KeywordScorer({"يوماً": 2.0}), article_scores=(0.0, 3.0), max_sentences=1
        ).answer("كم يوماً؟")
        assert answer.top is not None
        assert answer.top.article.article_id == "labor-law:75"
        assert answer.top.score == pytest.approx(1.0 + 3.0)

    def test_extra_sentences_come_only_from_the_best_article(self) -> None:
        scorer = KeywordScorer({"ستين": 6.0, "ثلاثين": 5.0, "مائة وثمانين": 5.5})
        answer = service(scorer, article_scores=(0.0, 1.0)).answer("كم المدة؟")
        assert [e.article.article_id for e in answer.evidence] == ["labor-law:75"] * 2
        assert [e.score for e in answer.evidence] == sorted(
            (e.score for e in answer.evidence), reverse=True
        )

    def test_max_sentences_caps_the_quotes(self) -> None:
        scorer = KeywordScorer({"يوماً": 5.0})
        assert len(service(scorer, max_sentences=1).answer("كم يوماً؟").evidence) == 1

    def test_extra_sentences_must_pass_the_threshold(self) -> None:
        scorer = KeywordScorer({"ستين": 5.0})
        assert len(service(scorer, threshold=1.0).answer("كم يوماً؟").evidence) == 1

    def test_scores_every_sentence_in_one_batch_with_the_location(self) -> None:
        scorer = KeywordScorer({})
        service(scorer).answer("سؤال")
        [batch] = scorer.calls
        assert len(batch) == len(split_sentences(PROBATION)) + len(split_sentences(NOTICE))
        assert all(passage.startswith("نظام العمل | المادة") for _, passage in batch)

    def test_rejects_a_scorer_that_loses_scores(self) -> None:
        with pytest.raises(InvalidDomainObjectError, match="Scorer returned"):
            service(ShortScorer()).answer("سؤال")

    def test_no_articles_means_not_found(self) -> None:
        empty = AnswerService(SearchService(FakeRetriever([], [])), KeywordScorer({}), threshold=0)
        assert empty.answer("سؤال").status is AnswerStatus.NOT_FOUND

    def test_validates_the_question(self) -> None:
        with pytest.raises(InvalidDomainObjectError):
            service(KeywordScorer({})).answer("  ")

    @pytest.mark.parametrize(("articles", "sentences"), [(0, 2), (3, 0)])
    def test_rejects_bad_limits(self, articles: int, sentences: int) -> None:
        search = SearchService(FakeRetriever([], []))
        with pytest.raises(InvalidDomainObjectError):
            AnswerService(
                search, KeywordScorer({}), threshold=0, articles=articles, max_sentences=sentences
            )

    def test_name_wraps_the_pipeline(self) -> None:
        assert service(KeywordScorer({})).name == "extractive(fake)"


# ----------------------------------------------------------------------- report


def gold(query_id: str, relevant: tuple[tuple[str, int], ...]) -> GoldQuery:
    return GoldQuery(query_id, "سؤال", relevant, "t", QueryStyle.FORMAL)


def answered(article_id_number: int) -> Answer:
    source = article(article_id_number, PROBATION)
    return Answer("سؤال", AnswerStatus.ANSWERED, (Evidence(source, "ولكل من الطرفين الحق", 2.0),))


REFUSED = Answer("سؤال", AnswerStatus.NOT_FOUND, ())


class TestQualityReport:
    def test_counts_and_rates(self) -> None:
        judged = (("labor-law:1", 2), ("labor-law:2", 1))
        report = summarize_answers(
            "svc",
            [
                (gold("q1", judged), answered(1)),  # attributed
                (gold("q2", judged), answered(2)),  # related only
                (gold("q3", judged), answered(9)),  # wrong article
                (gold("q4", judged), REFUSED),  # false refusal
            ],
            [REFUSED, answered(1)],
        )
        assert (report.attributed, report.relevant, report.false_refusals) == (1, 2, 1)
        assert report.attribution_accuracy == 0.25
        assert report.any_relevant_accuracy == 0.5
        assert report.false_refusal_rate == 0.25
        assert report.wrong_answer_rate == pytest.approx(1 / 3)
        assert report.correct_refusal_rate == 0.5
        data = report.to_dict()
        assert data["service"] == "svc"
        assert data["wrong_answer_rate"] == 0.3333
        json.dumps(data)

    def test_top_evidence_grade(self) -> None:
        query = gold("q1", (("labor-law:1", 2),))
        assert top_evidence_grade(query, answered(1)) == 2
        assert top_evidence_grade(query, answered(5)) == 0
        assert top_evidence_grade(query, REFUSED) == 0

    def test_empty_denominators_are_zero(self) -> None:
        report = AnswerQualityReport("svc", 0, 0, 0, 0, 0, 0)
        assert report.attribution_accuracy == report.correct_refusal_rate == 0.0

    def test_needs_gold_questions(self) -> None:
        with pytest.raises(InvalidDomainObjectError):
            summarize_answers("svc", [], [])

    def test_measure_answers_runs_the_service(self) -> None:
        svc = service(KeywordScorer({"ستين": 5.0}))
        report = measure_answers(
            svc,
            [gold("q1", (("labor-law:75", 2),))],
            [OutOfScopeQuestion("oos-1", "سؤال آخر", "t", QueryStyle.FORMAL)],
        )
        assert (report.attributed, report.correct_refusals) == (1, 0)
        assert report.service == "extractive(fake)"


# ---------------------------------------------------------------- out-of-scope set


class TestOutOfScopeSource:
    def write(self, tmp_path: Path, *lines: str) -> Path:
        path = tmp_path / "out_of_scope.v1.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_loads_questions(self, tmp_path: Path) -> None:
        record = {"_id": "oos-1", "text": "سؤال", "topic": "traffic", "style": "dialect"}
        [question] = JsonlOutOfScopeSource(
            self.write(tmp_path, json.dumps(record, ensure_ascii=False), "")
        ).load()
        assert (question.query_id, question.style) == ("oos-1", QueryStyle.DIALECT)

    @pytest.mark.parametrize(
        ("line", "message"),
        [
            pytest.param("{not json", "invalid JSON", id="bad-json"),
            pytest.param('{"_id": "x", "text": "t", "topic": "t"}', "invalid record", id="field"),
            pytest.param(
                '{"_id": "x", "text": " ", "topic": "t", "style": "formal"}', "id and", id="blank"
            ),
        ],
    )
    def test_rejects_bad_lines(self, tmp_path: Path, line: str, message: str) -> None:
        with pytest.raises(SourceFormatError, match=message):
            JsonlOutOfScopeSource(self.write(tmp_path, line)).load()

    def test_rejects_duplicates_and_missing_files(self, tmp_path: Path) -> None:
        line = '{"_id": "x", "text": "t", "topic": "t", "style": "formal"}'
        with pytest.raises(SourceFormatError, match="duplicate"):
            JsonlOutOfScopeSource(self.write(tmp_path, line, line)).load()
        with pytest.raises(SourceFormatError, match="not found"):
            JsonlOutOfScopeSource(tmp_path / "missing.jsonl").load()

    def test_the_committed_set_loads(self) -> None:
        questions = JsonlOutOfScopeSource(
            REPO_ROOT / "data" / "gold" / "out_of_scope.v1.jsonl"
        ).load()
        assert len(questions) >= 30
        assert {q.style for q in questions} >= {QueryStyle.FORMAL, QueryStyle.DIALECT}
        assert all(re.fullmatch(r"oos-\d{3}", q.query_id) for q in questions)
