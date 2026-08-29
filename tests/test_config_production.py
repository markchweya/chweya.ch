"""Production configuration refusal.

Section 5 of the brief requires that production refuses to start when the
supplied development passwords are still configured, and more generally when
weak or default credentials are present. These tests are the proof.

They matter more than most: the check only ever runs in production, so nothing
in day-to-day development would reveal that it had broken. It already broke
once, by reading a PostgresDsn attribute that does not exist.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import (
    Environment,
    Settings,
    UnsafeConfiguration,
    is_known_unsafe_credential,
)

# The development bootstrap values from the brief. Written here, in the test
# suite, rather than in application source, which is where the brief forbids
# them. Their digests are what the application carries.
DEV_DB_PASSWORD = "ZugDBTest123"
DEV_ADMIN_PASSWORD = "ZugAdminTest123"

SAFE_SECRET = "an-adequately-long-random-secret-key-for-tests-000"


def production_settings(**overrides: object) -> Settings:
    """Build production settings that are otherwise valid."""
    base: dict[str, object] = {
        "environment": Environment.PRODUCTION,
        "debug": False,
        "secret_key": SAFE_SECRET,
        "public_base_url": "https://dumi.example.ch",
        "database_url": "postgresql+psycopg://dumi:a-real-and-long-password@db:5432/dumi",
        "session_cookie_secure": True,
        "crawler_contact": "operations@example.ch",
        "malware_scanner_command": "clamdscan --no-summary --stdout",
        "bootstrap_admin_password": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestKnownUnsafeCredentials:
    def test_both_development_passwords_are_recognised(self) -> None:
        assert is_known_unsafe_credential(DEV_DB_PASSWORD)
        assert is_known_unsafe_credential(DEV_ADMIN_PASSWORD)

    def test_common_weak_values_are_recognised(self) -> None:
        for value in ("password", "changeme", "admin", "postgres", "123456"):
            assert is_known_unsafe_credential(value), value

    def test_a_real_password_is_not_flagged(self) -> None:
        assert not is_known_unsafe_credential("kY7#pQ2vLm9!wRt4Zx")


class TestProductionRefusals:
    def test_a_valid_production_configuration_is_accepted(self) -> None:
        settings = production_settings()
        assert settings.environment is Environment.PRODUCTION

    def test_refuses_the_development_database_password(self) -> None:
        with pytest.raises(UnsafeConfiguration) as caught:
            production_settings(
                database_url=f"postgresql+psycopg://dumi:{DEV_DB_PASSWORD}@db:5432/dumi"
            )
        assert "DATABASE_URL contains a known development or weak password" in str(caught.value)

    def test_refuses_the_development_admin_password(self) -> None:
        with pytest.raises(UnsafeConfiguration) as caught:
            production_settings(bootstrap_admin_password=DEV_ADMIN_PASSWORD)
        assert "BOOTSTRAP_ADMIN_PASSWORD" in str(caught.value)

    def test_refuses_a_short_secret_key(self) -> None:
        with pytest.raises(UnsafeConfiguration) as caught:
            production_settings(secret_key="short")
        assert "SECRET_KEY must be at least 32 characters" in str(caught.value)

    def test_refuses_a_weak_secret_key(self) -> None:
        with pytest.raises(UnsafeConfiguration) as caught:
            production_settings(secret_key="changeme")
        assert "SECRET_KEY" in str(caught.value)

    def test_refuses_plain_http(self) -> None:
        with pytest.raises(UnsafeConfiguration) as caught:
            production_settings(public_base_url="http://dumi.example.ch")
        assert "PUBLIC_BASE_URL must use https" in str(caught.value)

    def test_refuses_insecure_session_cookies(self) -> None:
        with pytest.raises(UnsafeConfiguration) as caught:
            production_settings(session_cookie_secure=False)
        assert "SESSION_COOKIE_SECURE" in str(caught.value)

    def test_refuses_debug_mode(self) -> None:
        with pytest.raises(UnsafeConfiguration) as caught:
            production_settings(debug=True)
        assert "DEBUG must be false" in str(caught.value)

    def test_refuses_a_crawler_with_no_contact(self) -> None:
        """A crawler that will not say who to contact should not run."""
        with pytest.raises(UnsafeConfiguration) as caught:
            production_settings(crawler_contact="")
        assert "CRAWLER_CONTACT" in str(caught.value)

    def test_refuses_uploads_with_no_malware_scanner(self) -> None:
        with pytest.raises(UnsafeConfiguration) as caught:
            production_settings(malware_scanner_command="")
        assert "MALWARE_SCANNER_COMMAND" in str(caught.value)

    def test_every_problem_is_reported_at_once(self) -> None:
        """An operator should fix everything in one pass, not one per restart."""
        with pytest.raises(UnsafeConfiguration) as caught:
            production_settings(
                debug=True,
                session_cookie_secure=False,
                public_base_url="http://dumi.example.ch",
                crawler_contact="",
            )
        message = str(caught.value)
        assert "DEBUG" in message
        assert "SESSION_COOKIE_SECURE" in message
        assert "PUBLIC_BASE_URL" in message
        assert "CRAWLER_CONTACT" in message

    def test_failure_messages_never_contain_the_credential(self) -> None:
        """A startup failure must not leak a password into logs or container status."""
        with pytest.raises(UnsafeConfiguration) as caught:
            production_settings(
                database_url=f"postgresql+psycopg://dumi:{DEV_DB_PASSWORD}@db:5432/dumi",
                bootstrap_admin_password=DEV_ADMIN_PASSWORD,
                secret_key="changeme",
            )
        message = str(caught.value)
        assert DEV_DB_PASSWORD not in message
        assert DEV_ADMIN_PASSWORD not in message
        assert "changeme" not in message


class TestDevelopmentIsPermissive:
    """Development must stay usable, or the checks get disabled instead of fixed."""

    def test_development_accepts_the_supplied_bootstrap_values(self) -> None:
        settings = Settings(  # type: ignore[call-arg]
            environment=Environment.DEVELOPMENT,
            secret_key="dev-secret",
            database_url=f"postgresql+psycopg://dumi:{DEV_DB_PASSWORD}@localhost:5432/dumi",
            bootstrap_admin_password=DEV_ADMIN_PASSWORD,
            session_cookie_secure=False,
            debug=True,
        )
        assert settings.environment is Environment.DEVELOPMENT


class TestAllowlistValidation:
    def test_an_empty_crawler_allowlist_is_refused(self) -> None:
        """An empty allowlist would mean crawl anything."""
        with pytest.raises(ValidationError):
            production_settings(crawler_allowed_hosts="   ,  ,")

    def test_hosts_are_normalised_to_lower_case(self) -> None:
        settings = production_settings(crawler_allowed_hosts="WWW.Zug.CH, zug.ch ")
        assert settings.allowed_hosts == ("www.zug.ch", "zug.ch")

    def test_user_agent_includes_the_contact(self) -> None:
        settings = production_settings(crawler_contact="ops@example.ch")
        assert "ops@example.ch" in settings.user_agent
