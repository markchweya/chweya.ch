"""The mark is the product's only status indicator.

CLAUDE.md forbids a typing indicator, a spinner and a loading dot anywhere,
on the grounds that the mark already reports its state through its own
motion. That makes the motion a requirement rather than decoration: if the
mark holds still while a question is being answered, the interface has no
status indicator at all, and the rule that removed the others is no longer
paying for itself.

Recorded during a ten-second wait, the mark measured still. The orbiting
lenses are drawn at 28px beside a message, where they blur into each other
behind a static highlight and a statically lit core. These tests pin the
motion that survives being scaled down, and pin that it stops for a visitor
who asked for less of it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MARK_CSS = Path("shared/brand/dumi-mark.css")
SPECIMEN = Path("shared/brand/preview.html")


@pytest.fixture(scope="module")
def css() -> str:
    return MARK_CSS.read_text(encoding="utf-8")


def _block(source: str, selector: str) -> str:
    """The declarations of the first rule with this selector."""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", source)
    assert match, f"no rule for {selector}"
    return match.group(1)


class TestThinkingCarriesMotion:
    def test_the_core_breathes_while_thinking(self, css: str) -> None:
        """A change of brightness across the whole core reads at 28px, which
        is the size the mark is drawn at beside a message."""
        assert "animation: dumi-breathe" in _block(
            css, '.dumi[data-state="thinking"] .dumi__core'
        )
        assert "@keyframes dumi-breathe" in css

    def test_the_halo_pulses_while_thinking(self, css: str) -> None:
        assert "animation: dumi-pulse" in _block(
            css, '.dumi[data-state="thinking"]::before'
        )

    def test_thinking_is_faster_than_listening(self, css: str) -> None:
        """Each state reports something true, so the more active state must
        not be the calmer one to look at."""
        periods = {
            state: float(
                re.search(
                    r"dumi-pulse ([\d.]+)s",
                    _block(css, f'.dumi[data-state="{state}"]::before'),
                ).group(1)
            )
            for state in ("listening", "thinking")
        }
        assert periods["thinking"] < periods["listening"]


class TestReducedMotion:
    @pytest.fixture(scope="class")
    def reduced(self, css: str) -> str:
        start = css.index("@media (prefers-reduced-motion: reduce)")
        return css[start : css.index("\n}", start)]

    def test_the_thinking_animations_stop(self, reduced: str) -> None:
        assert '.dumi[data-state="thinking"]::before { animation: none; }' in reduced
        assert (
            '.dumi[data-state="thinking"] .dumi__core { animation: none; }' in reduced
        )

    def test_thinking_still_lights_the_core(self, css: str) -> None:
        """With the breathing stopped, the declared opacity stands, so the
        state is still visible without any movement at all."""
        assert "opacity: 1" in _block(
            css, '.dumi[data-state="thinking"] .dumi__core'
        )


class TestTheSpecimenMatches:
    """preview.html carries the mark's rules verbatim so the specimen and the
    interface cannot drift apart. A change made in one and not the other is
    the drift the copy exists to prevent."""

    @pytest.fixture(scope="class")
    def specimen(self) -> str:
        return SPECIMEN.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "rule",
        [
            '.dumi[data-state="thinking"]::before',
            "@keyframes dumi-breathe",
            "animation: dumi-breathe 1.6s ease-in-out infinite",
        ],
    )
    def test_the_thinking_motion_is_in_the_specimen(
        self, specimen: str, rule: str
    ) -> None:
        assert rule in specimen


class TestNoSecondIndicator:
    """The rule the motion pays for: the mark is the only thing that moves.

    Matched against keyframe names rather than any mention of the words, so
    the comments explaining why the product has no spinner do not fail the
    test that keeps it from having one.
    """

    def test_no_stylesheet_declares_a_second_indicator(self) -> None:
        names = re.compile(r"@keyframes\s+([\w-]+)")
        for path in (Path("app/static/chat.css"), MARK_CSS):
            for name in names.findall(path.read_text(encoding="utf-8")):
                assert not re.search(
                    r"spin|typing|ellipsis|loading|progress", name, re.IGNORECASE
                ), f"{name} in {path}"
