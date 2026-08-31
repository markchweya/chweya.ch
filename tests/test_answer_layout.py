"""The display structure of a finished answer.

An answer is plain text whose only structure is line-based. These tests pin
the two pieces that turn it into something readable on a phone: the tidy
step that drops a trailing line of bare citation markers, and the block
splitter the template and the client script both follow.
"""

from app.retrieval.answer import tidy_layout
from app.retrieval.layout import answer_blocks


class TestTidyLayout:
    def test_a_trailing_line_of_bare_markers_is_dropped(self) -> None:
        text = "Der Pass kostet 40 Franken [1].\n\n[1] [2] [3]"
        assert tidy_layout(text) == "Der Pass kostet 40 Franken [1]."

    def test_a_marker_line_in_the_middle_is_dropped_too(self) -> None:
        text = "Erster Teil [1].\n[1] [2]\nZweiter Teil [2]."
        assert tidy_layout(text) == "Erster Teil [1].\nZweiter Teil [2]."

    def test_markers_inside_sentences_are_untouched(self) -> None:
        text = "Die Frist endet am 31. August [1]. Danach gilt [2]."
        assert tidy_layout(text) == text

    def test_runs_of_blank_lines_collapse_to_one(self) -> None:
        assert tidy_layout("Eins.\n\n\n\nZwei.") == "Eins.\n\nZwei."


class TestAnswerBlocks:
    def test_blank_lines_separate_paragraphs(self) -> None:
        blocks = answer_blocks("Erster Absatz.\n\nZweiter Absatz.")
        assert blocks == [
            {"kind": "paragraph", "text": "Erster Absatz."},
            {"kind": "paragraph", "text": "Zweiter Absatz."},
        ]

    def test_lines_within_a_paragraph_flow_together(self) -> None:
        blocks = answer_blocks("Eine Zeile.\nNoch eine Zeile.")
        assert blocks == [
            {"kind": "paragraph", "text": "Eine Zeile. Noch eine Zeile."}
        ]

    def test_hyphen_lines_become_one_list(self) -> None:
        blocks = answer_blocks("Mitbringen [1]:\n- Pass\n- Mietvertrag")
        assert blocks == [
            {"kind": "paragraph", "text": "Mitbringen [1]:"},
            {"kind": "list", "entries": ["Pass", "Mietvertrag"]},
        ]

    def test_numbered_lines_become_steps_with_their_start(self) -> None:
        blocks = answer_blocks("3. Formular senden\n4. Termin abwarten")
        assert blocks == [
            {"kind": "steps", "entries": ["Formular senden", "Termin abwarten"], "start": 3}
        ]

    def test_pipe_rows_become_a_table(self) -> None:
        blocks = answer_blocks("Herbstferien | 05.10. | 16.10.\nSportferien | 06.02. | 21.02.")
        assert blocks == [
            {
                "kind": "table",
                "rows": [
                    ["Herbstferien", "05.10.", "16.10."],
                    ["Sportferien", "06.02.", "21.02."],
                ],
            }
        ]

    def test_a_year_alone_does_not_start_a_step_list(self) -> None:
        """A sentence starting with a four-digit year must stay prose."""
        blocks = answer_blocks("2026. Das ist eine Jahreszahl.")
        assert blocks == [
            {"kind": "paragraph", "text": "2026. Das ist eine Jahreszahl."}
        ]

    def test_a_list_of_labelled_values_becomes_a_pairs_table(self) -> None:
        """Tabular data wearing bullets: every item is "Label: value"."""
        blocks = answer_blocks(
            "- Herbstferien: Sa 03.10.2026 - So 18.10.2026\n"
            "- Sportferien: Sa 06.02.2027 - So 21.02.2027"
        )
        assert blocks == [
            {
                "kind": "pairs",
                "rows": [
                    ["Herbstferien", "Sa 03.10.2026 - So 18.10.2026"],
                    ["Sportferien", "Sa 06.02.2027 - So 21.02.2027"],
                ],
            }
        ]

    def test_a_list_with_one_unlabelled_item_stays_a_list(self) -> None:
        blocks = answer_blocks("- Herbstferien: 03.10.2026\n- Mietvertrag")
        assert blocks[0]["kind"] == "list"

    def test_a_single_labelled_item_stays_a_list(self) -> None:
        """One row is not a table."""
        blocks = answer_blocks("- Herbstferien: 03.10.2026")
        assert blocks[0]["kind"] == "list"

    def test_a_mixed_answer_keeps_its_order(self) -> None:
        text = (
            "Die Ferien stehen fest [1].\n\n"
            "Herbstferien | 05.10. | 16.10.\n\n"
            "Bringen Sie mit:\n- Pass\n- Foto"
        )
        kinds = [block["kind"] for block in answer_blocks(text)]
        assert kinds == ["paragraph", "table", "paragraph", "list"]
