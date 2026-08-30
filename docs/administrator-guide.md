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

## Things you cannot do yet

Uploading documents, resolving contradictions in the interface, managing users,
and promoting an index version are not implemented. See
`docs/known-limitations.md`.

## When something looks wrong

Note the request id shown with the error. It identifies the exact request
without anybody storing the question.
