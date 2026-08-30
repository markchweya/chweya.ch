"""Regenerate the PDF fixtures.

    .venv/bin/python tests/fixtures/generate.py

Real PDFs rather than hand-written byte strings, so the parser is tested
against documents a PDF reader would also accept. reportlab is a development
dependency only; the application never generates PDFs.
"""

from __future__ import annotations

import pathlib

from reportlab.lib import pdfencrypt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = pathlib.Path(__file__).parent


def build() -> None:
    # A well-formed two-page document with an upper-case heading on each page.
    c = canvas.Canvas(str(OUT / "merkblatt.pdf"), pagesize=A4)
    c.setTitle("Merkblatt Anmeldung")
    c.setAuthor("Kanton Zug")
    c.drawString(72, 780, "1. ANMELDUNG BEI DER EINWOHNERKONTROLLE")
    c.drawString(72, 750, "Sie muessen sich innert 14 Tagen nach dem Zuzug anmelden.")
    c.drawString(72, 730, "Die Gebuehr betraegt CHF 20.-- pro Person.")
    c.showPage()
    c.drawString(72, 780, "2. ERFORDERLICHE UNTERLAGEN")
    c.drawString(72, 750, "Identitaetskarte oder Reisepass, Mietvertrag,")
    c.drawString(72, 730, "sowie ein Nachweis der Krankenversicherung.")
    c.showPage()
    c.save()

    # A page containing only a drawn rectangle, standing in for a scan with no
    # text layer.
    c = canvas.Canvas(str(OUT / "scan_no_text_layer.pdf"), pagesize=A4)
    c.rect(72, 600, 400, 150, fill=0)
    c.showPage()
    c.save()

    # Password protected, to confirm it is refused rather than attacked.
    enc = pdfencrypt.StandardEncryption("userpass", ownerPassword="ownerpass")
    c = canvas.Canvas(str(OUT / "encrypted.pdf"), pagesize=A4, encrypt=enc)
    c.drawString(72, 780, "Vertraulich")
    c.showPage()
    c.save()


if __name__ == "__main__":
    build()
    for path in sorted(OUT.glob("*.pdf")):
        print(f"{path.name}: {path.stat().st_size} bytes")
