"""Report what state the corpus is in, per canton.

    python -m app.cli corpus-health [--canton zug] [--json]

Exit code 0 when every canton would survive the three faults the Canton of
Lucerne named when it switched its assistant off after three days, 1
otherwise. So it can gate a launch, which is the point: Lucerne's problem was
not that the numbers were bad, it was that nobody had them until afterwards.
"""

from __future__ import annotations

import json
import sys

from app.cantons import CANTONS, normalise_canton
from app.db.session import session_scope
from app.evaluation.corpus import all_cantons_health, canton_health, format_report


def _as_dict(health) -> dict:  # type: ignore[no-untyped-def]
    return {
        "canton": health.canton,
        "sources": health.sources,
        "sources_paused": health.sources_paused,
        "sources_never_crawled": health.sources_never_crawled,
        "sources_crawl_overdue": health.sources_crawl_overdue,
        "documents": health.documents,
        "answerable_documents": health.answerable_documents,
        "chunks": health.chunks,
        "chunks_embedded": health.chunks_embedded,
        "fresh_chunks": health.fresh_chunks,
        "ageing_chunks": health.ageing_chunks,
        "stale_chunks": health.stale_chunks,
        "good_extraction": health.good_extraction,
        "partial_extraction": health.partial_extraction,
        "poor_extraction": health.poor_extraction,
        "failing_urls": health.failing_urls,
        "open_contradictions": health.open_contradictions,
        "languages": list(health.languages),
        "ready": health.ready,
        "charges": [
            {
                "key": charge.key,
                "question": charge.question,
                "verdict": charge.verdict,
                "detail": charge.detail,
            }
            for charge in health.charges
        ],
    }


def main(argv: list[str]) -> int:
    """Report corpus health. Returns a process exit code."""
    wanted: str | None = None
    if "--canton" in argv:
        index = argv.index("--canton")
        if index + 1 >= len(argv):
            print("--canton needs a value.", file=sys.stderr)
            return 2
        wanted = normalise_canton(argv[index + 1])
        if wanted not in CANTONS:
            print(
                f"Unknown canton {argv[index + 1]!r}. "
                f"Known: {', '.join(sorted(CANTONS))}.",
                file=sys.stderr,
            )
            return 2

    with session_scope() as session:
        reports = (
            [canton_health(session, wanted)] if wanted else all_cantons_health(session)
        )

    if "--json" in argv:
        print(json.dumps([_as_dict(health) for health in reports], indent=2))
    else:
        print(format_report(reports))

    return 0 if all(health.ready for health in reports) else 1
