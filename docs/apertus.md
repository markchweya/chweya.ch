# Apertus configuration

Apertus is the Swiss open language model. Dumi talks to it over the
OpenAI-compatible chat completions API, which both vLLM and Ollama expose, so
the serving framework is not assumed. Only the wire format is.

**No Apertus endpoint has been contacted from this repository.** The provider
is verified against a recorded contract. Confirming a live endpoint is a local
step, described below.

## Settings

| Variable | Default | Notes |
|---|---|---|
| `APERTUS_BASE_URL` | `http://localhost:8000/v1` | vLLM default. Ollama uses 11434. |
| `APERTUS_MODEL` | `apertus` | Must match what the server lists |
| `APERTUS_API_KEY` | empty | Only if the server requires one |
| `APERTUS_TIMEOUT_SECONDS` | 120 | A person is waiting |
| `APERTUS_MAX_CONTEXT_TOKENS` | 8192 | Must not exceed the model's window; 4096 is the practical floor, see below |
| `APERTUS_MAX_OUTPUT_TOKENS` | 1024 | Reserved from the context budget |
| `APERTUS_TEMPERATURE` | 0.2 | Low on purpose, see below |
| `APERTUS_MAX_RETRIES` | 2 | Transient failures only |
| `APERTUS_STREAM` | true | Supported by the provider |

### How small the context window may be

The system prompt is about 1000 tokens, and the reserve for the answer is
the output limit plus a small margin. Whatever remains is what the evidence
gets, so a tight window is a retrieval limit as much as a model limit: at
3072 context and 512 output only two or three passages fit, and a question
whose answer sits in the fourth is refused or answered from the wrong page.

4096 is the floor worth running for the 8B model on a laptop, and 8192 is
better where the machine allows it. On CPU the cost of the larger window is
mostly memory rather than time, because the prompt is processed once per
question. The window configured here must not exceed what the serving model
was started with; Ollama silently truncates a longer prompt otherwise, which
looks like the model ignoring its evidence.

The provider refuses a request whose prompt plus output exceeds the window
rather than letting the server truncate it, so a window set too small shows
up as a clear failure rather than as quietly worse answers.

### Why temperature is 0.2

This is grounded question answering. Sampling creativity does not produce a
more helpful answer; it produces invented fees and deadlines that read exactly
like the real ones. Raising it is a decision to accept that.

## Confirming a local endpoint

```bash
make apertus-check
```

Expected: `state: healthy` and the configured model in the list.

`degraded` with "not in the served list" means the server is running but under
a different model identifier. Set `APERTUS_MODEL` to what it reports.

`unavailable` means nothing answered. Check the server is running and that
`APERTUS_BASE_URL` includes the `/v1` suffix.

## Reaching the desktop from Docker

The containers cannot see `localhost`; that is the container's own loopback.
Use the host gateway, which `docker-compose.yml` already wires:

```
APERTUS_BASE_URL=http://host.docker.internal:11434/v1
```

Apertus is deliberately not a compose service. It already works on the
developer's desktop, and containerising a model server that works would
duplicate the weights and waste GPU memory for nothing.

## Failure behaviour

The system fails closed. Every failure raises rather than degrading into an
empty answer, and the chat surface says the assistant is unavailable. It never
answers from model memory.

- Connection failure, timeout, or a 5xx surviving retries: unavailable.
- A 4xx other than 429: refused immediately, not retried.
- An unparseable body: treated as a failure. It may be a proxy error page, and
  rendering that as an answer is worse than reporting the service down.
- A mid-stream parse failure: raises, so a truncated stream cannot look like a
  finished answer.
- `finish_reason: length`: surfaced as truncation and the answer carries a
  qualification, because a cut-off list of requirements reads as a complete one.

Error messages never include the response body. A misconfigured proxy can echo
an `Authorization` header, and there is a test asserting a bearer token in a
403 body does not reach the message.

## Production, and what Swiss hosting requires

Nothing about this code makes a deployment Swiss-hosted. Where the endpoint
runs is a deployment decision.

To deploy in Switzerland you need: a Swiss provider with adequate GPU capacity;
the model weights on that infrastructure; `APERTUS_BASE_URL` pointing at it
over TLS; an API key; network policy allowing only the application to reach
it; and **verification that it actually runs where you believe it does**.

Until that is verified, no document in this repository may claim Swiss hosting,
and none does.

## Upgrading the model

The prompt is tuned for a model that follows instructions and cites. Changing
model means re-running the evaluation suite before promoting anything:

```bash
make evaluate
```

The adversarial cases are the ones that matter. A new model that fails an
injection or disclosure case is not an upgrade.
