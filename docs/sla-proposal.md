# Proposed service level agreement

**No service level agreement exists. This is a draft for negotiation.** The
prototype carries no guarantees of any kind, and nothing in this repository
should be read as a commitment.

Every target below is a proposal with a stated basis, so it can be argued with
rather than accepted.

## Scope

The Dumi assistant, its administration interface, and the ingestion pipeline
for approved Canton of Zug sources. Excludes the availability of zug.ch, the
correctness of the canton's own published content, and any network the
provider does not control.

## Availability

| Target | Proposed | Basis |
|---|---|---|
| Monthly availability | 99.5% | About 3.6 hours a month. An information service, not an emergency one |
| Measurement | `/readyz` from two locations, one minute apart | |
| Exclusions | Planned maintenance announced 5 working days ahead; failure of an upstream the provider does not control | |

99.5% rather than 99.9% because the honest constraint is Apertus. A single
model server is a single point of failure, and promising three nines without
redundant inference would be promising something not built.

## Support hours

| Target | Proposed |
|---|---|
| Business hours | Monday to Friday, 08:00 to 17:00 CET, excluding Zug public holidays |
| Outside hours | Severity 1 only |

## Severity and response

| Severity | Definition | Response | Restoration target |
|---|---|---|---|
| 1 | Wrong information affecting a legal deadline or obligation; suspected data breach | 1 hour | 4 hours |
| 2 | Service unavailable; administrative access compromised; audit chain broken | 4 business hours | 1 business day |
| 3 | Degraded quality; ingestion failing | 1 business day | 5 business days |
| 4 | Cosmetic; documentation | 5 business days | Next release |

Wrong information is severity 1 and outranks an outage. An outage is visible
and recoverable. A confidently wrong deadline is neither, and it is the harm
this system is capable of causing.

## Content freshness

| Target | Proposed | Basis |
|---|---|---|
| Synchronisation | Every 24 hours | Cantonal content changes slowly |
| Maximum content age | 7 days | Allows for a failed run and a fix |
| Contradiction triage | 5 business days | |
| Deadline or fee contradiction triage | 1 business day | Highest consequence |

## Backup and recovery

| Objective | Proposed |
|---|---|
| Backup frequency | Daily, retained 30 days |
| Recovery point objective | 24 hours |
| Recovery time objective | 4 hours |
| Restore drill | Monthly, logged |

An RPO of 24 hours means up to a day of audit entries and uploads could be
lost. Crawled content is re-derivable; those two are not. If that is
unacceptable, continuous archiving is the answer and it costs more.

## Security incident notification

| Target | Proposed |
|---|---|
| Notify the canton of a suspected breach | 12 hours from detection |
| Written preliminary report | 72 hours |
| Full report | 10 working days |

Swiss notification duties are time-bound and are a legal matter. These targets
are operational and do not replace legal advice.

## Measurement and reporting

Monthly: availability, incidents by severity with response and restoration
times, synchronisation success rate, content age, open contradictions,
evaluation suite results, and any target missed with an explanation.

## What this agreement cannot promise

- **That answers are correct.** The system cites its sources and refuses when
  evidence is insufficient. It cannot guarantee an answer is right, and no
  service level can make it so.
- **That the canton's own content is correct.**
- **Legal, tax or medical advice.** The assistant does not provide it.
- **Any binding determination** on any individual case.

## Before this becomes an agreement

Someone must accept these targets and the cost of meeting them; the deployment
must exist and its data residency be verified; monitoring must be in place,
since an availability target nobody measures is a sentence rather than a
commitment; and the exclusions must be checked against what the canton
actually expects.
