# Staff training

Five short guides. Each ends with what to escalate, because knowing the
boundary matters more than knowing the procedure.

---

## Content administrators

**What you are responsible for:** what the assistant is allowed to read.

Adding a source widens what gets fetched. Check the host is on the allowlist,
the content is public, and robots.txt permits it. Then run a crawl and **read
what came back**. The blocked-reason counts on the run tell you what was
skipped and why.

Approving content means the assistant may quote it to residents. Read the
extracted text rather than the original page: if extraction mangled a table of
fees, the answer will be wrong even though the source is right.

**Escalate:** anything suggesting a canton page has been altered by someone
who should not have access. That is their security incident, not our content
problem, and it matters far more than our index.

---

## Contradiction reviewers

**What you are responsible for:** deciding which official statement is
currently correct, because the system deliberately will not.

You see two passages, both values, both dates. Ask: are these the same service?
Very often they are not, and **"not a contradiction" is the right answer**.

If they are the same service and the values differ, which page is current? The
dates help and do not settle it.

If you cannot tell, mark it unresolved rather than guessing. Answers will then
tell residents the sources appear inconsistent, which is honest.

**Escalate:** a contradiction where both values are plausible and the topic is
a deadline or a legal obligation. Ask the responsible office rather than
picking.

---

## Support operators

**What you are responsible for:** investigating reports that an answer was
wrong.

You will not find the question text. It is not stored, by design. You have the
request id, the confidence, the citations and the retrieval diagnostics.

Work backwards: what did it cite, and does that source actually say what the
answer claimed? Three different faults look identical from outside. The source
is wrong. The extraction is wrong. The model misread a correct source.

**Escalate:** an answer with no citations, which should be impossible and
means a bug; anything touching a legal deadline; anything suggesting the
assistant disclosed something it should not.

---

## Technical administrators

**What you are responsible for:** the system running, and its history staying
trustworthy.

Daily: `/readyz` and `python -m app.cli verify-audit`.

A broken audit chain is a security incident. **Do not repair the rows.** The
break is the evidence.

Rotating credentials: `make rotate-credentials` prints the procedure. It does
not perform it, because a half-rotated database password leaves the
application unable to connect.

Restore drills monthly. A backup nobody has restored is a hope.

**Escalate:** a broken audit chain, an administrative account you cannot
account for, any suspicion that data left the infrastructure it should be on.

---

## Security and privacy reviewers

**What you are responsible for:** the questions this project cannot answer for
itself.

Read `docs/threat-model.md` and `docs/privacy.md`, both of which list what is
implemented and what is not.

The claims worth checking hardest: that transcripts are not stored, that no
raw client address is stored, that question text never enters a log, and that
nothing is sent to a third-party AI service.

**You must decide, because nobody else can:** whether the DPIA is required and
whether the draft is adequate; whether the audit retention period is right;
whether crawling zug.ch is acceptable and whether the canton should be asked
first; and whether a Swiss hosting claim is verified rather than assumed.

**Nothing in this repository is legal advice, and no document in it claims
compliance.**
