# Support runbook

For whoever answers when someone says the assistant got it wrong.

## What you can and cannot see

You cannot see the question. It is not stored, deliberately.

You can see: the request id, the confidence, which sources were cited, whether
the answer was a refusal, and whether retrieval was degraded.

If someone reports a problem, ask for the request id shown with it. It
identifies the exact request without anybody storing what they asked.

## Triage

| Report | First check |
|---|---|
| "It gave the wrong fee/deadline" | What did it cite? Does the source say that? |
| "It said it didn't know" | Is the content indexed and embedded at all? |
| "It answered in the wrong language" | Which language was selected? Detection keeps the selection under 20 characters. |
| "The link is broken" | Has the canton moved the page? |
| "It told me something about my case" | Escalate immediately. It has no case data and must not appear to. |

## Three faults that look identical

An answer can be wrong because the canton's page is wrong, because extraction
mangled a correct page, or because the model misread a correct extraction.
Only reading the extracted text tells you which.

- **Source wrong:** tell the canton. Do not correct their content in our index.
- **Extraction wrong:** exclude the passage and file it as an extraction bug.
- **Model misread:** add a grounded evaluation case so it cannot regress
  silently.

## An answer with no citations

Should be impossible. The system replaces an uncited answer with the
insufficient-evidence response. If one appears, that is a bug, not a content
problem. Escalate.

## What to tell someone

Be plain. It is an unofficial prototype, it can be wrong, and the cited
official page is what counts. Do not defend an answer you have not checked.

If they acted on wrong information and it cost them something, escalate at
once. That is severity 1 in `docs/runbook-incident.md`.
