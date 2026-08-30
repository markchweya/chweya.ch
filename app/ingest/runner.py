"""Running a crawl in the background of the web process.

A crawl of a real site takes minutes to hours: robots.txt is respected, every
host gets at least a one-second gap between requests, and a source can cover
thousands of pages. That cannot run inside an HTTP request, so the button
schedules it onto the server's event loop and returns immediately. The
CrawlRun row is the progress report; the sources page reads it.

Two honest limits of this design, both documented in the deployment notes:

* The crawl lives in the web process. Restarting the server kills it, which
  is why startup marks any run still saying RUNNING as failed rather than
  letting it block the source forever. The compose worker service exists for
  moving this out of the web process later.
* The crawler awaits between requests, so the event loop stays responsive,
  but the post-crawl embedding step is CPU-bound and runs in a thread.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CrawlRun, CrawlRunState, Source
from app.db.session import get_session_factory
from app.ingest.crawler import Crawler
from app.ingest.fetcher import GuardedFetcher
from app.observability import get_logger
from app.retrieval.indexer import embed_pending_chunks, update_search_vectors

logger = get_logger(__name__)

# States that mean a run is (or claims to be) still going.
ACTIVE_RUN_STATES = (CrawlRunState.QUEUED.value, CrawlRunState.RUNNING.value)

# Belt to the database's braces: the set of source ids this process is
# currently crawling. The DB check alone has a small race window between two
# near-simultaneous clicks; this closes it within the process.
_active: set[uuid.UUID] = set()


def active_run_for(db: Session, source_id: uuid.UUID) -> CrawlRun | None:
    """Return the run currently claiming this source, if any."""
    return db.execute(
        select(CrawlRun)
        .where(CrawlRun.source_id == source_id, CrawlRun.state.in_(ACTIVE_RUN_STATES))
        .order_by(CrawlRun.started_at.desc().nullslast())
        .limit(1)
    ).scalar_one_or_none()


def fail_orphaned_runs(db: Session) -> int:
    """Mark runs that a dead process left saying RUNNING as failed.

    Called at startup. The crawl lives in the web process, so a restart kills
    it mid-run; without this, the stale row would block its source forever
    and the dashboard would show a crawl that is not happening.
    """
    orphans = list(
        db.execute(
            select(CrawlRun).where(CrawlRun.state.in_(ACTIVE_RUN_STATES))
        ).scalars()
    )
    for run in orphans:
        run.state = CrawlRunState.FAILED.value
        run.finished_at = dt.datetime.now(dt.UTC)
        run.error_summary = (run.error_summary + "\n" if run.error_summary else "") + (
            "interrupted: the server restarted while this run was active"
        )
    if orphans:
        logger.warning("crawl.orphaned_runs_failed", runs=len(orphans))
    return len(orphans)


async def _run_crawl(source_id: uuid.UUID, triggered_by_id: uuid.UUID | None) -> None:
    """Execute one crawl with its own session and fetcher, then index.

    Everything here answers to one rule: whatever happens, the CrawlRun row
    ends in a terminal state and the resources are closed. Crawler.run
    already records its own failure; this wraps the parts around it.
    """
    session = get_session_factory()()
    fetcher = GuardedFetcher()
    try:
        source = session.get(Source, source_id)
        if source is None:
            logger.error("crawl.source_vanished", source_id=str(source_id))
            return

        # commit_start makes the RUNNING row visible to every other session
        # immediately, so the sources page can show the crawl and a second
        # process cannot start a duplicate.
        run = await Crawler(session, fetcher).run(
            source, triggered_by_id=triggered_by_id, commit_start=True
        )
        session.commit()

        # Keyword retrieval works the moment this commits. Embedding loads a
        # model and is CPU-bound, so it runs in a thread; if no model is
        # available the semantic arm simply stays empty, which retrieval
        # already treats as a degraded search rather than a failure.
        indexed = update_search_vectors(session)
        session.commit()

        embedded = 0
        try:
            # The provider cache lives with the chat routes; reusing it means
            # the crawl and the chat share one loaded model and one failure
            # hold, instead of this module loading a second copy.
            from app.api.chat import get_embedding_provider

            provider = get_embedding_provider()
            # embed_pending_chunks works in bounded batches so one call cannot
            # hold memory for a whole site. Loop until it drains, committing
            # per batch, or a large crawl leaves its tail keyword-only: a 169
            # page run produced 583 chunks and a single batch stopped at 500.
            while True:
                batch = await asyncio.to_thread(embed_pending_chunks, session, provider)
                session.commit()
                embedded += batch
                if batch == 0:
                    break
        except Exception as exc:  # noqa: BLE001 - embeddings are best-effort here
            session.rollback()
            logger.warning("crawl.embedding_skipped", error=type(exc).__name__)

        logger.info(
            "crawl.background_run_finished",
            state=run.state,
            fetched=run.urls_fetched,
            versions=run.versions_created,
            search_vectors=indexed,
            embedded=embedded,
        )
    except Exception:
        # Crawler.run records its own failures; reaching here means something
        # around it broke (a lost database connection, most likely). The row
        # is repaired by fail_orphaned_runs at the next startup if this
        # session cannot do it now.
        session.rollback()
        logger.exception("crawl.background_run_crashed", source_id=str(source_id))
    finally:
        _active.discard(source_id)
        await fetcher.aclose()
        session.close()


def start_crawl(
    db: Session, source: Source, *, triggered_by_id: uuid.UUID | None
) -> list[str]:
    """Schedule a crawl of one source onto the running event loop.

    Returns problems as message keys; empty means the crawl is running.
    Must be called from a coroutine (an async route): the task has to land
    on the server's loop to outlive the request.
    """
    if source.is_paused:
        return ["crawl.source_paused"]
    if source.id in _active or active_run_for(db, source.id) is not None:
        return ["crawl.already_running"]

    _active.add(source.id)
    asyncio.get_running_loop().create_task(_run_crawl(source.id, triggered_by_id))
    logger.info("crawl.scheduled", source_id=str(source.id))
    return []
