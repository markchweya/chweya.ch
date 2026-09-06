"""Control characters in extracted text.

A mis-encoded PDF on a canton site came out of extraction with a NUL byte
between every character, and PostgreSQL refuses NUL in a text column. The
scrubber removes what the database cannot hold and keeps the words.
"""

from app.ingest.textclean import strip_control_characters


class TestStripControlCharacters:
    def test_interleaved_nuls_leave_the_words_intact(self) -> None:
        """The shape the mis-encoded PDF actually produced."""
        raw = "\x00o\x00l\x00z\x00b\x00a\x00c\x00h\x00 \x00(\x001\x005\x00.\x00)"
        cleaned, removed = strip_control_characters(raw)
        assert cleaned == "olzbach (15.)"
        assert removed == 13

    def test_newlines_and_tabs_survive(self) -> None:
        cleaned, removed = strip_control_characters("Zeile 1\nZeile 2\tSpalte\r\n")
        assert cleaned == "Zeile 1\nZeile 2\tSpalte\r\n"
        assert removed == 0

    def test_other_control_characters_go(self) -> None:
        cleaned, removed = strip_control_characters("a\x07b\x0cc\x1fd\x7fe")
        assert cleaned == "abcde"
        assert removed == 4

    def test_clean_text_is_returned_unchanged(self) -> None:
        text = "Die Anmeldung kostet CHF 20.-- pro Person."
        assert strip_control_characters(text) == (text, 0)
