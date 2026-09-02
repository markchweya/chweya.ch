"""Application configuration, loaded and validated from the environment.

Every setting arrives through an environment variable. Nothing here carries a
usable default for a credential, a host or a URL that would silently work in
production.

Validation happens at import time via :func:`get_settings`, so a misconfigured
deployment fails at startup with a clear message rather than at first use, in
the middle of a user request.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class UnsafeConfiguration(RuntimeError):
    """Raised when the configuration must not be used in production.

    Deliberately not a ValueError. Pydantic converts ValueError raised inside a
    validator into a ValidationError whose message includes the entire input,
    which for this model means the database password and the bootstrap
    administrator password. A startup failure would then print both to stderr
    and into the container log, which is precisely what the check exists to
    prevent. Any other exception type propagates untouched.

    This was found by the test asserting that a refusal message never contains
    the credential it refused.
    """


def safe_validation_report(exc: Exception) -> list[str]:
    """Render a pydantic ValidationError without any input values.

    pydantic includes the offending input in its default string form. For this
    model that can be a DSN containing a password, so error reporting always
    goes through here rather than through str(exc).
    """
    lines: list[str] = []
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return [str(exc)]
    for error in errors():
        location = ".".join(str(part) for part in error.get("loc", ())) or "(root)"
        # msg is pydantic's own description and never carries the value.
        lines.append(f"{location}: {error.get('msg', 'invalid')}")
    return lines


class Environment(StrEnum):
    """Deployment environment.

    ``production`` enables the credential and transport safety checks in
    :meth:`Settings.reject_unsafe_production_configuration`.
    """

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


# SHA-256 digests of credentials that must never reach production.
#
# The digests are stored rather than the plaintext because the brief forbids
# hardcoding the development bootstrap values into source. A digest lets the
# startup check recognise them without the repository containing a usable
# credential. Adding a value here is cheap; extend the list freely.
#
# Generated with: python -c "import hashlib,sys;
#   print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" "<value>"
KNOWN_UNSAFE_CREDENTIAL_DIGESTS: frozenset[str] = frozenset(
    {
        # The two development bootstrap values named in the project brief.
        "b04f6a5b4399ca5ecf3de98c25a5040a06db3a41fda31d1929d6df41b7456a72",
        "6510fe5a0b9accce3dd86942d713d40efd31f554a219385958a8ec8a2ab85f06",
        # Commonly used weak values.
        "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",
        "19513fdc9da4fb72a4a05eb66917548d3c90ff94d5419e1f2363eea89dfee1dd",
        "057ba03d6c44104863dc7361fe4578965d1887360f90a0895882e58a6248fc86",
        "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918",
        "4194d1706ed1f408d5e02d672777019f4d5385c766a8c6ca8acba3167d36a7b9",
        "a942b37ccfaf5a813b1432caa209a43b9d144e47ad0de1549c289c253e556cd5",
        "2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b",
        "1c8bfe8f801d79745c4631d09fff36c82aa37fc4cce4fc946683d7b336b63032",
        "8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92",
        "213f8d8f99fea0d5350a1ca3b7f951f1fd32ad8f8a502154ba61cc4b8544271e",
        "badc194db2c72e19accb589d987a3a2b588fb87a723194ef6b6ec610b1aaafb9",
        "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        "4813494d137e1631bba301d5acab6e7bb7aa74ce1185d456565ef51d737677b2",
        "ce5ca673d13b36118d54a7cf13aeb0ca012383bf771e713421b4d1fd841f539a",
        "280d44ab1e9f79b5cce2dd4f58f5fe91f0fbacdac9f7447dffc318ceb79f2d02",
        "65e84be33532fb784c48129675f9eff3a682b27168c0ea744b2cf58ee02337c5",
    }
)

SUPPORTED_LANGUAGES: tuple[str, ...] = ("de", "en", "fr", "it")
"""The four languages the assistant must answer in. German first: it is the
official language of the Canton of Zug and the language most sources are
published in."""


def is_known_unsafe_credential(value: str) -> bool:
    """Return True if ``value`` is a development bootstrap or known weak value.

    Compares digests so that no plaintext credential appears in this module.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest() in KNOWN_UNSAFE_CREDENTIAL_DIGESTS


class Settings(BaseSettings):
    """Validated application settings.

    Field names map to upper-case environment variables, so ``database_url``
    is read from ``DATABASE_URL``. See ``.env.example`` for the full list.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------------------------------------------------------- core
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False

    # Signs session cookies. Must be high-entropy and unique per deployment.
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
    secret_key: SecretStr

    # Public origin, used to build absolute URLs and to set cookie scope.
    public_base_url: str = "http://localhost:8000"

    # ------------------------------------------------------------ database
    database_url: PostgresDsn
    database_pool_size: Annotated[int, Field(ge=1, le=100)] = 10
    database_max_overflow: Annotated[int, Field(ge=0, le=100)] = 5
    # Statement timeout in milliseconds. Prevents one pathological retrieval
    # query from holding a connection open indefinitely.
    database_statement_timeout_ms: Annotated[int, Field(ge=1000, le=300_000)] = 30_000

    # --------------------------------------------------------------- redis
    redis_url: RedisDsn = "redis://localhost:6379/0"  # type: ignore[assignment]

    # ------------------------------------------------------------- Apertus
    # Apertus is reached over an OpenAI-compatible chat completions API, which
    # is what both vLLM and Ollama expose. The serving framework is therefore
    # not assumed; only the wire format is.
    apertus_base_url: str = "http://localhost:8000/v1"
    apertus_model: str = "apertus"
    apertus_api_key: SecretStr | None = None
    apertus_timeout_seconds: Annotated[float, Field(gt=0, le=600)] = 120.0
    apertus_connect_timeout_seconds: Annotated[float, Field(gt=0, le=60)] = 10.0
    apertus_max_context_tokens: Annotated[int, Field(ge=1024, le=1_000_000)] = 8192
    apertus_max_output_tokens: Annotated[int, Field(ge=64, le=32_000)] = 1024
    # Low by default. This is a grounded question-answering system, and
    # sampling creativity here shows up as invented fees and deadlines.
    apertus_temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.2
    apertus_max_retries: Annotated[int, Field(ge=0, le=10)] = 2
    apertus_stream: bool = True
    apertus_health_timeout_seconds: Annotated[float, Field(gt=0, le=60)] = 5.0

    # ---------------------------------------------------------- embeddings
    # Self-hosted only. Must cover de, en, fr and it.
    embedding_model: str = "intfloat/multilingual-e5-base"
    embedding_dimensions: Annotated[int, Field(ge=64, le=4096)] = 768
    embedding_batch_size: Annotated[int, Field(ge=1, le=256)] = 16

    # ------------------------------------------------------------- crawler
    # Hostnames the crawler is permitted to contact. Anything not on this list
    # is refused before a socket is opened. See app/ingest/allowlist.py.
    #
    # Both portals are included because the names are easily confused:
    # zg.ch is the Canton of Zug, zug.ch is the City of Zug. Residents ask
    # about both levels of government, and the cantonal content lives on
    # zg.ch.
    crawler_allowed_hosts: str = (
        "www.zug.ch,zug.ch,www.zg.ch,zg.ch,www.uri.ch,uri.ch"
    )
    crawler_user_agent: str = "DumiBot/0.1 (unofficial prototype; +{contact})"
    # Required. A crawler that does not say who to contact should not run.
    crawler_contact: str = ""
    crawler_max_concurrency: Annotated[int, Field(ge=1, le=16)] = 2
    crawler_default_delay_seconds: Annotated[float, Field(ge=0.0, le=60.0)] = 1.0
    crawler_max_response_bytes: Annotated[int, Field(ge=1024, le=200 * 1024 * 1024)] = 25 * 1024 * 1024
    crawler_request_timeout_seconds: Annotated[float, Field(gt=0, le=300)] = 30.0
    crawler_max_redirects: Annotated[int, Field(ge=0, le=10)] = 3
    crawler_max_pages_per_run: Annotated[int, Field(ge=1, le=1_000_000)] = 5000
    crawler_respect_robots: bool = True

    # --------------------------------------------------------- file upload
    upload_max_bytes: Annotated[int, Field(ge=1024, le=500 * 1024 * 1024)] = 50 * 1024 * 1024
    upload_storage_path: str = "./storage/uploads"
    upload_quarantine_path: str = "./storage/quarantine"
    # Integration point for a malware scanner. Empty disables scanning, which
    # is acceptable in development and refused in production.
    malware_scanner_command: str = ""

    # ------------------------------------------------------------- privacy
    # Conversations are not retained by default. Section 14 of the brief
    # requires data minimisation, and nothing about answering a question needs
    # the transcript afterwards.
    store_chat_transcripts: bool = False
    chat_retention_days: Annotated[int, Field(ge=0, le=3650)] = 0
    # Store a salted hash of the client address for abuse control rather than
    # the address itself.
    hash_client_addresses: bool = True

    # -------------------------------------------------------- rate limits
    rate_limit_chat_per_minute: Annotated[int, Field(ge=1, le=1000)] = 12
    rate_limit_login_per_minute: Annotated[int, Field(ge=1, le=100)] = 5
    login_max_failures: Annotated[int, Field(ge=1, le=100)] = 5
    login_lockout_seconds: Annotated[int, Field(ge=10, le=86_400)] = 900

    # -------------------------------------------------------- sessions
    session_cookie_name: str = "dumi_session"
    session_idle_timeout_minutes: Annotated[int, Field(ge=1, le=1440)] = 60
    session_absolute_timeout_hours: Annotated[int, Field(ge=1, le=168)] = 12
    # Set false only for plain-HTTP local development. Refused in production.
    session_cookie_secure: bool = True
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # ---------------------------------------------------- admin bootstrap
    # Used once by "python -m app.cli bootstrap-admin". The password is hashed
    # with Argon2id immediately and never stored in plaintext.
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: SecretStr | None = None

    # --------------------------------------------------------- observability
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # ------------------------------------------------------------ validators
    @field_validator("crawler_allowed_hosts")
    @classmethod
    def _reject_empty_allowlist(cls, value: str) -> str:
        """An empty allowlist would mean "crawl anything", so refuse it."""
        if not [h.strip() for h in value.split(",") if h.strip()]:
            raise ValueError("CRAWLER_ALLOWED_HOSTS must list at least one hostname")
        return value

    @field_validator("public_base_url", "apertus_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def allowed_hosts(self) -> tuple[str, ...]:
        """The crawler hostname allowlist, normalised to lower case."""
        return tuple(
            h.strip().lower() for h in self.crawler_allowed_hosts.split(",") if h.strip()
        )

    @property
    def database_password(self) -> str | None:
        """Return the password embedded in DATABASE_URL, if any.

        PostgresDsn has no ``.password`` attribute; credentials are only
        reachable through ``hosts()``. Wrapped here because the production
        safety check depends on it, and reaching into the structure at each
        call site is how that check silently broke once already.
        """
        hosts = self.database_url.hosts()
        if not hosts:
            return None
        return hosts[0].get("password")

    @property
    def database_host(self) -> str | None:
        """Return the database hostname, for diagnostics that must not print the DSN."""
        hosts = self.database_url.hosts()
        return hosts[0].get("host") if hosts else None

    @property
    def user_agent(self) -> str:
        """The crawler User-Agent with the contact address substituted in."""
        return self.crawler_user_agent.replace("{contact}", self.crawler_contact)

    @model_validator(mode="after")
    def reject_unsafe_production_configuration(self) -> Settings:
        """Refuse to start in production with unsafe configuration.

        Required by section 5 of the brief. The checks are grouped and reported
        together so an operator fixes everything in one pass rather than
        discovering the next problem on the next restart.

        Failure messages name the offending environment variable and never
        include the value, so a startup failure cannot leak a credential into
        a log or a container status message.
        """
        if self.environment is not Environment.PRODUCTION:
            return self

        problems: list[str] = []

        # Session signing key.
        secret = self.secret_key.get_secret_value()
        if len(secret) < 32:
            problems.append("SECRET_KEY must be at least 32 characters in production")
        if is_known_unsafe_credential(secret):
            problems.append("SECRET_KEY is a known development or weak value")

        # Database password, extracted from the DSN so a bootstrap value in the
        # connection string is caught too.
        db_password = self.database_password
        if db_password is None or db_password == "":
            problems.append("DATABASE_URL must include a password in production")
        elif is_known_unsafe_credential(db_password):
            problems.append("DATABASE_URL contains a known development or weak password")

        # Administrator bootstrap password, if one is still configured.
        if self.bootstrap_admin_password is not None:
            candidate = self.bootstrap_admin_password.get_secret_value()
            if is_known_unsafe_credential(candidate):
                problems.append(
                    "BOOTSTRAP_ADMIN_PASSWORD is a known development or weak value. "
                    "Unset it in production once the administrator exists."
                )

        # Transport and cookie security.
        if not self.session_cookie_secure:
            problems.append("SESSION_COOKIE_SECURE must be true in production")
        if not self.public_base_url.startswith("https://"):
            problems.append("PUBLIC_BASE_URL must use https in production")
        if self.session_cookie_samesite == "none" and not self.session_cookie_secure:
            problems.append("SESSION_COOKIE_SAMESITE=none requires SESSION_COOKIE_SECURE=true")

        # Operational requirements that are optional in development.
        if self.debug:
            problems.append("DEBUG must be false in production")
        if not self.crawler_contact.strip():
            problems.append("CRAWLER_CONTACT must name a reachable contact in production")
        if not self.malware_scanner_command.strip():
            problems.append(
                "MALWARE_SCANNER_COMMAND must be configured in production, because "
                "administrator uploads are accepted"
            )

        if problems:
            raise UnsafeConfiguration(
                "Refusing to start in production with unsafe configuration:\n  - "
                + "\n  - ".join(problems)
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, validated once and cached.

    Cached because validation is not free and the environment does not change
    while the process runs. Tests clear the cache with
    ``get_settings.cache_clear()``.
    """
    return Settings()  # type: ignore[call-arg]
