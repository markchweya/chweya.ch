# Three-year maintenance plan

Extends `docs/maintenance-2-year.md`. Years 1 and 2 are unchanged; this
document is about what a third year is actually for.

## Year 3

A third year only makes sense if the system is being kept rather than
finished. The work changes shape.

**Model and retrieval currency.** Two years is long enough for the embedding
model to be clearly outdated. Replacing it means re-embedding the whole corpus
and, if dimensions change, a migration and an index rebuild. Budget for it as
a project rather than a patch.

**Platform currency.** A Python or PostgreSQL major version upgrade is likely
in this window. Both are routine and neither is free.

**Corpus growth.** Retrieval quality degrades as a corpus grows if nothing is
retired. Expect to need: a reranker, retirement of superseded content from the
active index, and index tuning. The version history stays; the active index
should not.

**Institutional memory.** The people who understand the system in year 1 may
not be there in year 3. This is what the documentation and the training guides
exist for, and they need reviewing against what people actually ask.

## What to reconsider rather than continue

**Does the canton want to adopt it?** After two years there is evidence. If yes,
the unofficial framing comes off and the engagement changes fundamentally. If
no, that is worth knowing rather than continuing by default.

**Is the confidence policy right?** By year 3 there is real data on how often
it refuses and how often those refusals were correct. That is the first point
at which the thresholds can be set from evidence rather than judgement.

**Is the contradiction queue being read?** If it has grown without being
worked, the honest response is to change the detection thresholds or drop the
feature, not to let a queue nobody reads sit there implying oversight that is
not happening.

**Is the crawl still welcome?** Two years of crawling a site somebody else
operates is worth re-confirming.

## Risks specific to a longer engagement

| Risk | Response |
|---|---|
| Apertus development stalls | The provider abstraction means another OpenAI-compatible model can be substituted, with re-evaluation |
| Corpus grows past what one server retrieves quickly | Index tuning, then partitioning |
| Nobody reviews contradictions | Reduce detection sensitivity or remove the feature |
| The canton publishes a competing assistant | Wind down rather than compete with the source of truth |
| Documentation drifts | Annual review, treated as delivery work |

## What still cannot be promised

The same three things as in year 1: that answers are correct, that the
canton's content is correct, and that any answer is a binding determination.
Nothing about a longer engagement changes those.
