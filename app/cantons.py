"""The canton registry.

One Dumi serves several cantons. Everything that differs between them lives
in ``cantons/<slug>/canton.json``: the display name, the portal, the crawl
hosts, the accent token, and the per-language phrases the interface strings
splice in. Everything else, the interface, the answering rules, the safety
checks, is shared, which is the point of the repository layout.

The registry is read once at import. A deployment picks its cantons by what
the folder contains; the interface offers whatever is here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CANTONS_DIR = Path("cantons")

DEFAULT_CANTON = "zug"


@dataclass(frozen=True)
class Canton:
    """One canton a Dumi deployment can serve."""

    slug: str
    # The word beside "Dumi" in the lockup and in the canton menu.
    label: str
    # The portal residents verify against: "zg.ch", linked to portal_url.
    portal_label: str
    portal_url: str
    # Hostnames this canton's sources may live on. The global crawl
    # allowlist still applies at fetch time; this scopes a source to its
    # canton at creation time.
    hosts: tuple[str, ...]
    # Languages the canton publishes in. The interface languages are shared.
    languages: tuple[str, ...]
    # The one token a canton may override; see shared/brand/dumi-tokens.css.
    accent_rgb: str
    # Per-language pieces the interface strings splice in. Full phrases
    # rather than bare names, because the grammar differs by canton: French
    # writes "de Zoug" but "d'Uri", Italian "del Cantone di Zugo" but
    # "del Canton Uri".
    names: dict[str, str]
    of_phrases: dict[str, str]
    by_phrases: dict[str, str]

    def name(self, language: str) -> str:
        return self.names.get(language) or self.label

    def of_phrase(self, language: str) -> str:
        return self.of_phrases.get(language) or self.of_phrases["de"]

    def by_phrase(self, language: str) -> str:
        return self.by_phrases.get(language) or self.by_phrases["de"]


def _load() -> dict[str, Canton]:
    cantons: dict[str, Canton] = {}
    for path in sorted(CANTONS_DIR.glob("*/canton.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        canton = Canton(
            slug=data["slug"],
            label=data["label"],
            portal_label=data["portal_label"],
            portal_url=data["portal_url"],
            hosts=tuple(data["hosts"]),
            languages=tuple(data["languages"]),
            accent_rgb=data["accent_rgb"],
            names=data["names"],
            of_phrases=data["of_phrases"],
            by_phrases=data["by_phrases"],
        )
        cantons[canton.slug] = canton
    if DEFAULT_CANTON not in cantons:
        raise RuntimeError(f"cantons/{DEFAULT_CANTON}/canton.json is required")
    return cantons


CANTONS: dict[str, Canton] = _load()


def normalise_canton(slug: str | None) -> str:
    """An unknown or missing canton falls back to the default.

    The chat page must render something sensible for any query string, and
    the default canton is the honest fallback rather than an error page.
    """
    if slug and slug.strip().lower() in CANTONS:
        return slug.strip().lower()
    return DEFAULT_CANTON


def get_canton(slug: str | None = None) -> Canton:
    return CANTONS[normalise_canton(slug)]
