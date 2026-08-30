# Administrator guide

For staff who manage sources, documents and users.

## Signing in

`/admin/login`. On a first sign-in with a bootstrap password you are sent
straight to the password change and nothing else is reachable until it is
done. That is deliberate: the bootstrap credential is good for exactly one
login.

The current password is required even for that forced change, so a session
left open on an unattended machine cannot be used to take the account over.
Changing your password signs out every other session.

Five failed attempts lock the account for fifteen minutes. Wait, or ask a
super administrator.

## Roles

| Role | Can |
|---|---|
| Super administrator | Everything, including users and configuration |
| Content administrator | Sources, uploads, approving content |
| Reviewer | Resolve contradictions, review flagged answers |
| Support operator | Read anonymised feedback and diagnostics |
| Auditor | Read audit events and system state, change nothing |

A person can hold several. Give the narrowest set that lets someone do their
job; that is what the roles are for.

Nobody, including a super administrator, can view a stored password hash.

## The dashboard

Every figure is a live count. If something reads zero, it is zero.

The two to watch: **passages embedded** against **passages total**, because a
gap means part of the corpus is invisible to semantic search; and **awaiting
review**, because that content cannot be used until somebody looks.

## Sources

A source is an area of a site the crawler may fetch. Adding one widens what
the system will fetch, so it is a policy decision and it is audited.

Before adding: the host must be on the allowlist, the content must be public,
and robots.txt must permit it. See `docs/source-policy.md`.

After a crawl, read what came back before trusting it. The first crawl of a
real site always surfaces boilerplate the filters have not seen.

## Documents

Approved content is retrievable. `awaiting_review` is not, and content lands
there automatically when it carries an injection flag or when extraction
quality was poor.

Reviewing one means reading the extracted text, not the original page. If the
extraction is wrong, the answer will be wrong even though the source is right.

Publication state is separate from review state. A draft that you approve is
still a draft and will never reach the public index. That separation is
deliberate.

## Contradictions

The queue lists suspected inconsistencies, highest priority first. Deadlines
outrank fees because missing a deadline has consequences a resident cannot
undo.

You are not being asked which page is prettier. You are being asked which one
is currently correct, and **"not a contradiction" is a legitimate and common
answer** when two different services simply charge different amounts.

If you cannot tell, mark it unresolved. Answers touching it will then say the
official sources appear inconsistent, which is true and useful.

## Uploading a document

`/admin/uploads` takes PDF, DOCX, TXT, Markdown, CSV and HTML. The file goes
through validation, a malware scan and text extraction before you see anything,
and it lands in the list with whatever state it reached.

A refusal names what was wrong. "Content does not match extension" means the
bytes are not what the name claims, which is worth checking with whoever sent
you the file. "No text could be extracted" from a PDF almost always means a
scan with no text layer, and there is no text recognition here, so that
document has to be supplied in another form.

Then you supply the metadata. None of it is guessed from the file, because a
PDF's own title field is usually the name of the document its author started
from, and its language is often absent or wrong. What you type is what a
citation shows a resident:

| Field | What it is for |
| --- | --- |
| Title | The heading a resident sees beside the answer |
| Responsible office | Who to contact. Name the office a resident would ask for |
| Language | Decides how the text is indexed. Wrong here means never found |
| Publication state | Only official and supplementary can be approved |
| Publication date | The date the document itself carries |
| Valid from, valid until | When it applies, if it says |

Read the extracted text on the same page before approving. That is what
retrieval will use. A source that is correct and an extraction that is garbled
produce a wrong answer with a correct citation, which is the worst combination
available.

Approving needs the approval permission and puts the document into the public
index. Until somebody approves it, nothing you upload can answer anything.

## Replacing, withdrawing and deleting

**Replace** when a newer edition of the same document arrives. It becomes a
further version, the old one is kept, and citations already given stay
explicable. Approve the replacement to make it the one that answers.

**Withdraw** when the document stopped applying but nothing replaced it: a fee
that was abolished, a form that was pulled. It leaves the index, the file and
the version stay, and your reason is recorded. A reason is required.

**Delete** when the file should not be there at all. The bytes, the extracted
text and the passages go. The record of the upload and the version row stay, so
a citation issued before the deletion can still be explained. This is not an
erasure of every trace, and it should not be described to anyone as one.

Every upload, replacement, download, approval, withdrawal and deletion is on
the audit record, including downloading the original.

## Things you cannot do yet

Resolving contradictions in the interface, managing users, and promoting an
index version are not implemented. See `docs/known-limitations.md`.

## When something looks wrong

Note the request id shown with the error. It identifies the exact request
without anybody storing the question.
