# Contradiction review

## What the system does

Notices that two passages about apparently the same subject state different
fees, deadlines, contact numbers or opening hours, and files a finding.

## What it deliberately does not do

Decide which one is right.

Section 9 prohibits it, and the reason is worth stating: two Zug pages giving
different fees might be a stale page, two genuinely different services, or a
typo. Nothing available to the detector distinguishes those. A system that
picked a winner would put a wrong fee in front of residents with its own
confidence behind it.

## How a finding is raised

Two passages are compared only when they come from **different documents** and
share at least three long subject terms. A page listing several fees is a
price list, not a contradiction, and two unrelated services legitimately
charging different amounts is not one either.

Precision is favoured over recall. Every finding costs a reviewer's attention,
and a queue full of false positives is a queue nobody reads, which is worse
than no queue.

## Priority

| Kind | Base | Why |
|---|---|---|
| Deadline | 90 | Missing one has consequences a resident cannot undo |
| Eligibility | 80 | Sends someone to the wrong place entirely |
| Fee | 70 | Corrected at the counter, but erodes trust |
| Contact | 60 | Wastes a journey |
| Translation mismatch | 50 | One language community gets worse information |
| Opening hours | 40 | Annoying, rarely serious |

A fee gap of CHF 100 or more raises the fee priority; a gap under CHF 5 lowers
it.

## Resolving one

A reviewer sees both passages, both extracted values, both documents with
their dates and versions, and the shared terms that caused the comparison.

| Resolution | Use when |
|---|---|
| First is current | The first passage is right and the second is out of date |
| Second is current | The reverse |
| Both excluded | Neither should be used until the canton clarifies |
| Not a contradiction | Two different services, or a difference that is correct |
| Unresolved | Needs the canton to answer, and until then answers must say so |

**"Not a contradiction" will be the most common outcome**, and that is fine.
Without it a reviewer has to force a real distinction into a resolution
implying one page is wrong.

Every resolution is audited with the reviewer's identity, the outcome and any
note.

## Effect on answers

While a finding touching a passage is open, in review, or unresolved, an
answer drawing on that passage lowers its confidence and tells the user the
official sources appear inconsistent.

A passage in a version marked excluded or superseded is not retrievable at all.

## The interface

`/admin/review` lists open findings, most urgent first, with the recent
decisions below them. It requires the contradiction-resolution permission,
which the reviewer role holds and the auditor deliberately does not.

The detail page shows both passages in full with their documents, versions,
dates and extracted values. Each resolution option states its consequence on
the form itself, because a reviewer must know that a choice takes a page out
of the index before making it.

What each decision does:

* **Not a contradiction** records the judgment and touches no content.
* **First or second is current** excludes the version carrying the stale
  passage. The exclusion self-heals: when the canton fixes the page, the next
  crawl files a new version and its approval is a fresh decision.
* **Both excluded** takes both versions out of the index.
* **Unresolved** keeps the finding open, and with it the qualification on
  every answer touching either passage.

Any decision that removes content requires a written reason. A decided
finding stays decided; if the situation changes, detection files a new one.
"Start review" marks a finding as being looked at, advisorily: it tells a
second reviewer someone is on it, and locks nothing.

Detection can be run from the queue page. Filing findings decides nothing,
so a reviewer may trigger it, and the run is audited.

The effect on answers is wired in: an answer drawing on a passage party to an
open, in-review or unresolved finding is capped at low confidence and carries
the inconsistency notice in the user's language.
