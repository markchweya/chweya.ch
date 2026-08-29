"""Report the effective configuration and what production would refuse.

    python -m app.cli check-config

Prints setting names and non-secret values. Secrets are shown only as whether
they are set, never as their value, so the output is safe to paste into a
support ticket.

Running with ENVIRONMENT=production performs the production safety checks
without starting the application, which is how a deployment pipeline can fail
early rather than at first request.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.config import Environment, Settings, get_settings


def _mask(value: object) -> str:
    """Render a value, replacing anything secret with a set/unset marker."""
    if value is None or value == "":
        return "(not set)"
    return "(set)"


def main(argv: list[str]) -> int:
    """Print configuration and validate it. Returns a process exit code."""
    try:
        settings = get_settings()
    except ValidationError as exc:
        print("Configuration is invalid:\n")
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"])
            # error["msg"] is pydantic's message and never contains the value.
            print(f"  {location}: {error['msg']}")
        return 2

    print(f"Environment           : {settings.environment}")
    print(f"Debug                 : {settings.debug}")
    print(f"Public base URL       : {settings.public_base_url}")
    print(f"Secret key            : {_mask(settings.secret_key.get_secret_value())}")
    print()
    # Reported field by field. The DSN is never printed whole, because it
    # contains the password.
    dsn = settings.database_url
    print(f"Database host         : {settings.database_host}")
    print(f"Database name         : {dsn.path.lstrip('/') if dsn.path else '(none)'}")
    print(f"Database password     : {_mask(settings.database_password)}")
    print()
    print(f"Apertus base URL      : {settings.apertus_base_url}")
    print(f"Apertus model         : {settings.apertus_model}")
    print(f"Apertus API key       : {_mask(settings.apertus_api_key.get_secret_value() if settings.apertus_api_key else None)}")
    print(f"Apertus streaming     : {settings.apertus_stream}")
    print(f"Apertus temperature   : {settings.apertus_temperature}")
    print()
    print(f"Crawler allowlist     : {', '.join(settings.allowed_hosts)}")
    print(f"Crawler contact       : {settings.crawler_contact or '(not set)'}")
    print(f"Crawler user agent    : {settings.user_agent}")
    print(f"Respect robots.txt    : {settings.crawler_respect_robots}")
    print()
    print(f"Store transcripts     : {settings.store_chat_transcripts}")
    print(f"Hash client addresses : {settings.hash_client_addresses}")
    print(f"Malware scanner       : {settings.malware_scanner_command or '(not configured)'}")
    print(f"Session cookie secure : {settings.session_cookie_secure}")

    if settings.environment is Environment.PRODUCTION:
        print("\nProduction checks passed.")
        return 0

    # Re-validate the same values as if this were production, so an operator
    # can see what would be refused before attempting a deployment.
    print("\nSimulating production checks against the current values:")
    candidate = settings.model_dump()
    candidate["environment"] = Environment.PRODUCTION
    try:
        Settings(**candidate)
    except ValidationError as exc:
        for error in exc.errors():
            print(f"  {error['msg']}")
        print("\nThis configuration would be refused in production.")
        return 1

    print("  No problems found. This configuration would be accepted in production.")
    return 0
