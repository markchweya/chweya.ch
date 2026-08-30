# Crawler policy

What Dumi's crawler fetches, what it refuses, and why.

**Needs review by someone with authority to accept the legal risk of crawling
a site the project does not own.** Nothing here has been agreed with the
Canton of Zug.

## Scope

Public informational pages under the configured hostnames, currently
`www.zug.ch` and `zug.ch`. Widening the list is a policy decision, not a
configuration change, and it is audited.

"Crawl almost everything" means public, useful, informational content that is
legally and technically accessible. It does not mean ignoring exclusions,
technical restrictions, privacy, licensing or capacity limits.

## Never fetched

- Anything off the hostname allowlist.
- Anything robots.txt disallows for our user agent.
- Authenticated, administrative or internal paths, refused by URL pattern
  before robots.txt is even consulted.
- Search result pages, calendar views and other unbounded URL spaces.
- Anything requiring a form submission, a login or a CAPTCHA.
- Any non-HTTP scheme.
- Any address that is not public: loopback, private, link-local, carrier-grade
  NAT, reserved, or cloud metadata.

## Never done

- No state-changing request. GET and HEAD only.
- No form submission.
- No attempt to bypass a technical control of any kind.
- No crawling of a host the allowlist does not name, however a link arrived.

## Politeness

One request per host per second by default. A `Crawl-delay` in robots.txt can
only widen that gap, never narrow it. Concurrency is capped. Conditional
requests mean an unchanged page costs one round trip and no body.

The user agent identifies the crawler and carries a contact address.
Production refuses to start without one: a crawler that will not say who to
contact should not be running against someone else's website.

## When robots.txt cannot be read

A 404 or 410 means no rules are published, so everything public is allowed.

A 5xx, a timeout, a transport failure or a 403 means we do not know the rules,
and the **entire host is treated as disallowed** until robots.txt can be read.
Treating an unreadable robots.txt as permission is how a crawler ends up
somewhere it was told to stay out of.

## What is recorded

For every URL: the original and canonical form, HTTP status, failure reason,
ETag and Last-Modified, content hash, first seen, last fetched, last changed.
For every run: counts of fetched, unchanged, failed and blocked, with blocks
broken down by cause.

Only hostnames are logged, never full URLs. A path on a cantonal site can name
a very specific service, and an operational log should not accumulate a record
of exactly what was fetched when.

## Stopping

An administrator can pause a source, exclude a URL, or cancel a run. There is
no schedule yet, so nothing runs unattended.

If the Canton of Zug asks the crawler to stop, pause every source and remove
the hostnames from the allowlist. Both take effect immediately, and neither
requires a deployment.

## Open questions for review

1. Has anyone read the zug.ch terms of use against this policy?
2. Should the canton be told before a first full crawl?
3. Is there a preferred contact address for the user agent?
4. Is there a time window the canton would prefer for crawling?
