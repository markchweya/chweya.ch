"""How a citation number is set in the text.

Every factual sentence in an answer carries one, so a small typographic
error here is repeated a dozen times down the page. It was: the marker was
styled as a pill with a minimum width and side padding, which is twice as
wide as one digit, and its background sits at 18% alpha where nobody sees
it. What reached the screen was the word, a gap, the number, another gap and
then a stranded full stop, on every cited line of the answer.

The server already strips the space the model writes before a marker. These
tests pin both halves: the text arrives tight, and the stylesheet leaves it
that way.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.api.chat import cite_marks

CHAT_CSS = Path("app/static/chat.css")


class TestTheMarkupIsTight:
    def test_the_space_before_a_marker_is_removed(self) -> None:
        assert cite_marks("Die Frist endet am 31. März [8].") == (
            'Die Frist endet am 31. März<sup class="cite">8</sup>.'
        )

    def test_a_marker_without_a_leading_space_is_unchanged(self) -> None:
        assert cite_marks("Kosten[2].") == 'Kosten<sup class="cite">2</sup>.'

    def test_adjacent_markers_stay_separate_elements(self) -> None:
        """Two passages supporting one sentence must not merge into one
        number. The separator between them is drawn in CSS; what matters
        here is that they remain two elements to draw it between."""
        assert cite_marks("Zwei Belege [1][12].") == (
            'Zwei Belege<sup class="cite">1</sup><sup class="cite">12</sup>.'
        )

    def test_the_text_is_escaped_before_any_tag_is_written(self) -> None:
        assert "<b>" not in cite_marks("<b>fett</b> [1].")


class TestTheMarkerIsNotAPill:
    @pytest.fixture(scope="class")
    def rule(self) -> str:
        css = CHAT_CSS.read_text(encoding="utf-8")
        match = re.search(r"^\.cite\s*\{([^}]*)\}", css, re.MULTILINE)
        assert match, "no .cite rule"
        return match.group(1)

    @pytest.mark.parametrize(
        "declaration", ["min-width", "padding", "background", "margin-left"]
    )
    def test_the_marker_declares_no_width_of_its_own(
        self, rule: str, declaration: str
    ) -> None:
        """Any of these puts space back between the word, the number and the
        punctuation that follows them."""
        assert declaration not in rule

    def test_the_marker_is_raised_and_tinted(self, rule: str) -> None:
        assert "vertical-align" in rule
        assert "var(--dumi-flow)" in rule

    def test_adjacent_markers_are_separated(self) -> None:
        """Without this [1][12] reads as passage 112."""
        css = CHAT_CSS.read_text(encoding="utf-8")
        assert re.search(r"\.cite \+ \.cite::before\s*\{[^}]*content:", css)
