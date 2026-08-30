"""robots.txt handling.

The crawler obeys robots.txt. This is not only politeness: section 6 of the
brief forbids bypassing technical controls, and a rule in robots.txt is the
site operator stating what they do not want crawled.

Failure behaviour is deliberate and asymmetric:

* 404 or 410 means the site publishes no rules, so everything public is
  allowed. That is what the standard says and what every crawler does.
* 5xx, a timeout or a connection failure means we do not know what the rules
  are. Crawling anyway would risk ignoring a disallow that exists, so the host
  is treated as fully disallowed until robots.txt can be read.

The second case is the one that matters. Treating an unreadable robots.txt as
permission is how a crawler ends up in a place it was told to stay out of.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from app.observability import get_logger

logger = get_logger(__name__)

# How long a fetched robots.txt is trusted before it is re-read. Long enough
# that a crawl run does not re-fetch it repeatedly, short enough that a
# newly added disallow takes effect within a day.
CACHE_TTL_SECONDS = 6 * 3600

# A robots.txt larger than this is not a robots.txt. Google caps at 500 KiB.
MAX_ROBOTS_BYTES = 512 * 1024


@dataclass
class RobotsPolicy:
    """Parsed rules for one host."""

    host: str
    # None means "no rules published", which allows everything.
    parser: RobotFileParser | None = None
    # True when robots.txt could not be read and the host must be left alone.
    unreadable: bool = False
    crawl_delay_seconds: float | None = None
    sitemaps: tuple[str, ...] = ()
    fetched_at: float = field(default_factory=time.monotonic)

    def is_expired(self, ttl: float = CACHE_TTL_SECONDS) -> bool:
        return (time.monotonic() - self.fetched_at) > ttl

    def allows(self, url: str, user_agent: str) -> bool:
        """Return whether ``url`` may be fetched under these rules."""
        if self.unreadable:
            # We could not read the rules, so we do not know that we are
            # allowed. Assume not.
            return False
        if self.parser is None:
            return True
        return self.parser.can_fetch(user_agent, url)


def parse_robots(body: str, host: str, user_agent: str) -> RobotsPolicy:
    """Parse robots.txt content into a policy.

    Sitemap lines are collected separately, because RobotFileParser exposes
    them only when at least one rule group was parsed, and a robots.txt that
    is nothing but Sitemap lines is common.
    """
    parser = RobotFileParser()
    parser.parse(body.splitlines())

    delay = parser.crawl_delay(user_agent)
    try:
        crawl_delay = float(delay) if delay is not None else None
    except (TypeError, ValueError):
        crawl_delay = None

    # Read Sitemap directives directly rather than relying on site_maps(),
    # which returns None when no user-agent group was present.
    sitemaps: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("sitemap:"):
            value = stripped.split(":", 1)[1].strip()
            if value and value not in sitemaps:
                sitemaps.append(value)

    return RobotsPolicy(
        host=host,
        parser=parser,
        crawl_delay_seconds=crawl_delay,
        sitemaps=tuple(sitemaps),
    )


class RobotsCache:
    """Fetches and caches robots.txt per host.

    One instance per crawl run. Holding it for the life of the process would
    mean a rule added mid-week is not noticed until a restart.
    """

    def __init__(self, fetcher, user_agent: str, ttl: float = CACHE_TTL_SECONDS):  # type: ignore[no-untyped-def]
        self._fetcher = fetcher
        self._user_agent = user_agent
        self._ttl = ttl
        self._cache: dict[str, RobotsPolicy] = {}

    async def policy_for(self, url: str) -> RobotsPolicy:
        """Return the policy for the host of ``url``, fetching it if needed."""
        host = urlsplit(url).hostname or ""
        cached = self._cache.get(host)
        if cached is not None and not cached.is_expired(self._ttl):
            return cached

        scheme = urlsplit(url).scheme or "https"
        robots_url = f"{scheme}://{host}/robots.txt"
        result = await self._fetcher.fetch(robots_url)

        if result.ok and result.status_code == 200:
            body = result.content[:MAX_ROBOTS_BYTES].decode("utf-8", errors="replace")
            policy = parse_robots(body, host, self._user_agent)
            logger.info(
                "robots.loaded",
                host=host,
                sitemaps=len(policy.sitemaps),
                crawl_delay=policy.crawl_delay_seconds,
            )
        elif result.status_code in (401, 403):
            # Access to robots.txt is restricted. Treat the whole host as off
            # limits rather than guessing.
            logger.warning("robots.forbidden", host=host, status=result.status_code)
            policy = RobotsPolicy(host=host, unreadable=True)
        elif result.status_code in (404, 410):
            # No rules published, so nothing is disallowed.
            logger.info("robots.absent", host=host)
            policy = RobotsPolicy(host=host, parser=None)
        else:
            # 5xx, a timeout, or a transport failure. We do not know the rules.
            logger.warning("robots.unreadable", host=host, reason=result.reason or "unknown")
            policy = RobotsPolicy(host=host, unreadable=True)

        self._cache[host] = policy
        return policy

    async def allows(self, url: str) -> tuple[bool, str]:
        """Return whether ``url`` may be crawled, and why not when it may not."""
        policy = await self.policy_for(url)
        if policy.unreadable:
            return False, "robots_unreadable"
        if not policy.allows(url, self._user_agent):
            return False, "robots_disallowed"
        return True, ""
