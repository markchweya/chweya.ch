"""Removing what a database column cannot hold.

PostgreSQL text refuses NUL bytes, and a PDF whose fonts were mis-encoded
comes out of extraction with a NUL between every character: "olzbach" as
"\\x00o\\x00l\\x00z\\x00b\\x00a\\x00c\\x00h". The words are all there once the
NULs go, so they are removed rather than the page discarded. The other C0
control characters are dropped with them; none carries meaning in prose,
and a form feed or a bell in the middle of a passage is noise to the model
and to the reader. Newline, tab and carriage return stay.
"""

from __future__ import annotations

import re

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_control_characters(text: str) -> tuple[str, int]:
    """Return the text without control characters, and how many were removed."""
    cleaned, removed = _CONTROL.subn("", text)
    return cleaned, removed
