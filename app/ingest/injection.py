"""Detecting instruction-like text in retrieved content.

Everything Dumi retrieves is untrusted, including pages the Canton of Zug
publishes itself. A page can be edited, a PDF can be uploaded by someone whose
account was taken over, and a document can carry text designed to be read by a
language model rather than by a person.

What this module is, and is not:

It is a flag. It marks documents that contain text shaped like an instruction,
so a reviewer looks at them and so an answer drawing on them can be treated
with more caution.

It is not the defence. Section 13 says so explicitly: pattern detection alone
does not provide security. The actual defence is architectural and lives
elsewhere:

* Retrieved content is passed in a user-role message inside an explicit
  evidence block. It never occupies the system role.
* The model is given no tools, so there is nothing for injected text to
  invoke.
* Answers must cite retrieved evidence, so an instruction to ignore the
  evidence produces an answer that fails its own citation requirement.

Treating detection as the defence would be worse than having none, because it
invites relying on a filter that any determined phrasing gets past. False
negatives here are expected. False positives are cheap: a reviewer looks at a
page that turned out to be fine.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Invisible characters fall into two groups, and conflating them would make
# the detector useless on German content.
#
# Soft hyphens are ordinary. German CMSes emit them throughout compound words
# so the browser can hyphenate Einwohnerkontrolle sensibly. A page can contain
# hundreds legitimately, so they are stripped silently and never counted as a
# signal.
BENIGN_INVISIBLE = re.compile(r"[\u00ad]")

# These have no legitimate use in cantonal content. Zero-width spaces and
# joiners hide text from a human reviewer while a tokeniser still reads it,
# and bidi overrides can reverse displayed text so what a reviewer sees is not
# what the model receives.
SUSPICIOUS_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")

# Patterns are grouped by what they suggest, so a finding says something more
# useful than "suspicious". Written for German, English, French and Italian,
# because a page on a Zug site is far more likely to be in German.
PATTERN_GROUPS: dict[str, tuple[re.Pattern[str], ...]] = {
    "override_instruction": (
        re.compile(r"\bignor\w*\s+(?:all\s+|previous\s+|prior\s+|the\s+)*instruction", re.I),
        re.compile(r"\bdisregard\s+(?:all\s+|previous\s+|prior\s+|the\s+)*(?:instruction|rule|prompt)", re.I),
        re.compile(r"\bignorier\w*\s+(?:alle\w*\s+|vorherige\w*\s+|die\s+)*anweisung", re.I),
        re.compile(r"\bignor\w*\s+(?:toutes\s+|les\s+)*instructions", re.I),
        re.compile(r"\bignora\w*\s+(?:tutte\s+|le\s+)*istruzioni", re.I),
        re.compile(r"\bforget\s+(?:everything|all|your\s+instructions)", re.I),
        re.compile(r"\bvergiss\s+(?:alles|deine\s+anweisungen)", re.I),
    ),
    "role_reassignment": (
        re.compile(r"\byou\s+are\s+now\s+(?:a|an|the)\b", re.I),
        re.compile(r"\bdu\s+bist\s+(?:jetzt|nun)\s+(?:ein|eine|der|die)\b", re.I),
        re.compile(r"\bact\s+as\s+(?:a|an|the)\b", re.I),
        re.compile(r"\bverhalte\s+dich\s+wie\b", re.I),
        re.compile(r"\bnew\s+(?:system\s+)?(?:prompt|instruction|role)\s*[:=]", re.I),
        re.compile(r"\bneue\s+(?:system\w*\s+)?anweisung\s*[:=]", re.I),
        re.compile(r"^\s*system\s*[:=]", re.I | re.M),
    ),
    "secret_extraction": (
        re.compile(r"\b(?:reveal|print|show|repeat|output)\s+(?:your\s+)?(?:system\s+)?prompt", re.I),
        re.compile(r"\b(?:zeige|nenne|gib)\s+(?:mir\s+)?(?:deinen?\s+)?system[\w-]*\s*prompt", re.I),
        re.compile(r"\b(?:api[\s_-]?key|access[\s_-]?token|credential|passwor[dt])\b.{0,40}\b(?:show|reveal|print|zeige|nenne)\b", re.I),
        re.compile(r"\bwhat\s+(?:are|were)\s+your\s+(?:original\s+)?instructions\b", re.I),
    ),
    "citation_suppression": (
        # The most damaging kind for this product: an instruction that would
        # make an answer drop its sources.
        re.compile(r"\b(?:do\s+not|don't|never)\s+(?:cite|mention|show)\s+(?:the\s+)?(?:source|citation|reference)", re.I),
        re.compile(r"\b(?:zitiere|nenne)\s+(?:keine|nicht)\s+(?:quellen|referenzen)", re.I),
        re.compile(r"\banswer\s+without\s+(?:citing|sources|references)", re.I),
    ),
    "authority_claim": (
        # Text asserting that the content itself is authoritative, which is a
        # way of trying to outrank the real source ranking.
        re.compile(r"\bthis\s+(?:document|page)\s+(?:overrides|supersedes|replaces)\s+all\b", re.I),
        re.compile(r"\bdieses?\s+(?:dokument|seite)\s+(?:ersetzt|ueberschreibt)\s+alle\b", re.I),
        re.compile(r"\balways\s+(?:answer|respond|say)\s+that\b", re.I),
    ),
    "delimiter_forgery": (
        # Attempts to close the evidence block and start a new turn.
        re.compile(r"</?\s*(?:evidence|context|document|system|user|assistant)\s*>", re.I),
        re.compile(r"\[/?(?:INST|SYS|SYSTEM)\]", re.I),
        re.compile(r"<\|(?:im_start|im_end|endoftext|system|user|assistant)\|>", re.I),
        re.compile(r"^\s*###\s*(?:system|instruction|new\s+prompt)\b", re.I | re.M),
    ),
}


@dataclass(frozen=True)
class InjectionFinding:
    """One suspicious span."""

    category: str
    # A short excerpt, so a reviewer can see what triggered the flag without
    # opening the whole document.
    excerpt: str
    position: int


@dataclass(frozen=True)
class InjectionScan:
    """The result of scanning one document."""

    findings: tuple[InjectionFinding, ...] = ()
    # Zero-width and bidi characters removed. Soft hyphens are excluded from
    # this count, so a non-zero value here is genuinely anomalous rather than
    # a side effect of German hyphenation.
    invisible_characters_removed: int = 0

    @property
    def is_suspicious(self) -> bool:
        return bool(self.findings) or self.invisible_characters_removed > 2

    @property
    def categories(self) -> tuple[str, ...]:
        seen: list[str] = []
        for finding in self.findings:
            if finding.category not in seen:
                seen.append(finding.category)
        return tuple(seen)


def strip_invisible(text: str) -> tuple[str, int]:
    """Remove invisible characters, returning the text and a suspicion count.

    Soft hyphens are removed without contributing to the count, because German
    hyphenation uses them legitimately and in quantity. Zero-width and bidi
    characters are removed and counted, because nothing on a cantonal page has
    a reason to contain them.
    """
    cleaned = BENIGN_INVISIBLE.sub("", text)
    cleaned, suspicious = SUSPICIOUS_INVISIBLE.subn("", cleaned)
    return cleaned, suspicious


def normalise_for_scanning(text: str) -> str:
    """Normalise text so lookalike characters cannot evade the patterns.

    NFKC folds compatibility forms, so fullwidth and mathematical alphanumeric
    variants of "ignore" become the ordinary letters. Without this, a single
    substituted character defeats every pattern.
    """
    cleaned, _ = strip_invisible(text)
    return unicodedata.normalize("NFKC", cleaned)


def scan(text: str, *, excerpt_chars: int = 120) -> InjectionScan:
    """Scan text for instruction-like content.

    Reports every category that matched, not just the first, because a
    document combining role reassignment with citation suppression is more
    concerning than one doing either alone.
    """
    if not text:
        return InjectionScan()

    _, removed = strip_invisible(text)
    haystack = normalise_for_scanning(text)

    findings: list[InjectionFinding] = []
    for category, patterns in PATTERN_GROUPS.items():
        for pattern in patterns:
            match = pattern.search(haystack)
            if match is None:
                continue
            start = max(0, match.start() - 20)
            excerpt = haystack[start : match.end() + excerpt_chars].replace("\n", " ").strip()
            findings.append(
                InjectionFinding(category=category, excerpt=excerpt[:excerpt_chars], position=match.start())
            )
            # One finding per category is enough to route the document to a
            # reviewer. Listing every match would bury the signal.
            break

    return InjectionScan(findings=tuple(findings), invisible_characters_removed=removed)
