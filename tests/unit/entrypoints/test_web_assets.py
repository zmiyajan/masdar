"""Static checks on the web UI: Arabic-first, accessible, and CSP-compatible."""

import re
from html.parser import HTMLParser

import pytest

from masdar.entrypoints.api import WEB_DIR

INDEX = (WEB_DIR / "index.html").read_text(encoding="utf-8")
SCRIPT = (WEB_DIR / "app.js").read_text(encoding="utf-8")


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.script_bodies: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))
        self._in_script = tag == "script"

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script and data.strip():
            self.script_bodies.append(data)


@pytest.fixture(scope="module")
def page() -> _Collector:
    collector = _Collector()
    collector.feed(INDEX)
    return collector


def test_document_is_arabic_and_right_to_left(page: _Collector) -> None:
    [(_, html)] = [t for t in page.tags if t[0] == "html"]
    assert (html["lang"], html["dir"]) == ("ar", "rtl")


def test_no_inline_script_handlers_or_styles(page: _Collector) -> None:
    # The CSP allows only same-origin scripts and stylesheets.
    assert not page.script_bodies
    scripts = [attrs for tag, attrs in page.tags if tag == "script"]
    assert scripts
    assert all(attrs.get("src") for attrs in scripts)
    assert all(not name.startswith("on") for _, attrs in page.tags for name in attrs)
    assert all("style" not in attrs for _, attrs in page.tags)
    assert not [tag for tag, _ in page.tags if tag == "style"]


def test_only_self_and_google_fonts_are_loaded(page: _Collector) -> None:
    external = {
        attrs.get("href") or attrs.get("src")
        for tag, attrs in page.tags
        if tag in {"link", "script"} and attrs.get("rel") != "preconnect"
    } - {None}
    remote = {url for url in external if url and url.startswith("http")}
    assert remote == {url for url in remote if url.startswith("https://fonts.googleapis.com/")}


def test_the_script_never_injects_html() -> None:
    assert not re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write", SCRIPT)


def test_legal_disclaimer_is_present() -> None:
    assert "ليس استشارة قانونية — تحقق دائماً من المصدر الرسمي" in INDEX


def test_search_input_has_a_label(page: _Collector) -> None:
    labels = {attrs.get("for") for tag, attrs in page.tags if tag == "label"}
    assert "q" in labels


def test_example_questions_are_offered() -> None:
    # Which examples answer and which are refused is checked against the real
    # models in tests/integration/test_demo_examples.py.
    assert len(example_questions()) >= 4


def test_links_to_the_repository() -> None:
    assert "https://github.com/zmiyajan/masdar" in INDEX


def example_questions() -> list[str]:
    """The questions on the example chips, in page order."""
    return re.findall(r'data-question="([^"]+)"', INDEX)


def test_only_question_chips_trigger_a_search() -> None:
    # The sample-contract button shares the chip style but carries no question.
    assert 'querySelectorAll(".chip[data-question]")' in SCRIPT
