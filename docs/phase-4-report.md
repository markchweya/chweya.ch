# Phase 4 report: retrieval and chat

Status at commit `04e0e31`. 358 tests passing.

## Verified working

Against a live PostgreSQL 16 with pgvector 0.6.0, seeded by a real crawl.

**Hybrid retrieval.** Semantic over pgvector with an HNSW index, keyword over
`tsvector` with a GIN index, fused by reciprocal rank fusion. A passage found
by both arms outranks one found first by only one.

**Language-aware search.** Each language is matched with the PostgreSQL text
search configuration its column was indexed with, falling back to `simple`
rather than English.

**The confidence policy.** Computed from evidence properties before the model
runs, never by the model. Every downgrade records a named reason.

**Insufficient evidence refuses without calling the model.**

**Citations** carry title, official URL, section or PDF page, source language
and last-checked date. Invented citation markers are stripped; an answer with
no citations at all is replaced.

**The chat surface** runs on the existing Dumi design system, works without
JavaScript, and is localised into all four languages.

**Fail-closed behaviour.** An unavailable model says so rather than answering
from memory.

## Findings that changed behaviour

**Vector search made insufficient-evidence nearly unreachable.** Nearest
neighbour search returns its k results whatever the distance, so a question
about dog tax in Reykjavik retrieved the closest Zug pages and the model was
called. A cosine distance floor now discards distant matches.

**German compounds defeated the risk patterns.** `\bbewilligung\b` cannot
match *Baubewilligung*, so a building permit question carried no high-risk
notice. Terms that form the tail of a compound are now unanchored.

**Keyword search returned nothing for partial matches.**
`websearch_to_tsquery` joins terms with AND, so *Einwohnerkontrolle Frist*
missed a page containing only the first term. An OR retry runs when the strict
query finds nothing.

**Alembic emitted a migration that would not run.** It renders
`pgvector.sqlalchemy.Vector` without importing it. `env.py` now adds the
import.

**`CREATE EXTENSION` needs superuser.** The migration now fails with the exact
command an operator must run instead of a bare permission error.

**Tests read the developer's `.env`.** A production-refusal test passed or
failed depending on local configuration.

## Not implemented

- **Streaming.** The provider supports it and the UI has a stop control; the
  endpoint returns a complete answer. The live region and stop button are
  built for streaming and currently have little to announce incrementally.
- **Reranking.** Fusion is RRF only. A cross-encoder reranker is the usual
  next step.
- **Contradiction detection.** Phase 5.
- **Conversation memory.** Each question is answered independently. Follow-up
  questions referring to a previous answer will not resolve.

## Environment limitations

**No embedding model has ever run.** The network policy permits PyPI and
blocks huggingface.co, so weights cannot be downloaded here.
`sentence-transformers` is installed and its provider is tested against a
stub covering dimension checking and prefix selection. All retrieval testing
used the non-semantic `HashingProvider`, which matches on shared vocabulary
rather than meaning.

This matters for one number in particular: `MAX_SEMANTIC_DISTANCE` is set to
0.62 and has been calibrated against nothing. With a real model it will need
tuning against real Zug content, and it directly controls how often the
assistant says it cannot verify something. Too low and it refuses good
questions; too high and insufficient-evidence stops working.

**No Apertus endpoint has been contacted.** Every answering test uses a stub.

## Requires human review

- The confidence thresholds encode a judgement about when a public body should
  answer and when it should defer. They deserve review by someone accountable
  for that.
- The high-risk topic list should be checked against the canton's own view of
  which services carry risk.
- The German, French and Italian interface strings need review by native
  speakers. They were written by a model and are not authoritative.
