"""Malware scanning.

An integration point rather than a scanner. The command is configured, and
production refuses to start without one, because accepting administrator
uploads with no scanning configured is a decision nobody should be able to
make by forgetting.

The scanner runs against a file in quarantine. Nothing is promoted to accepted
storage until it has passed, so a file that is never scanned is never served.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from enum import StrEnum

from app.config import Environment, Settings, get_settings
from app.observability import get_logger

logger = get_logger(__name__)

# subprocess is imported deliberately: running the operator-configured scanner
# is this module's entire purpose. It is invoked with an argv list and no
# shell, so a file path can never become part of a command line.

# A scan that has not finished in this time is treated as a failure. A scanner
# hanging must not hold a request or leave a file in an undefined state.
SCAN_TIMEOUT_SECONDS = 120


class ScanOutcome(StrEnum):
    """What a scan concluded."""

    CLEAN = "clean"
    INFECTED = "infected"
    # The scanner could not reach a verdict. Treated as not clean.
    FAILED = "failed"
    # No scanner is configured. Permitted in development, refused in
    # production by the configuration check.
    NOT_CONFIGURED = "not_configured"

    @property
    def may_promote(self) -> bool:
        """Whether a file with this outcome may leave quarantine.

        NOT_CONFIGURED permits promotion because development would otherwise
        be unusable. Production cannot reach this state: it will not start
        without MALWARE_SCANNER_COMMAND set.
        """
        return self in (ScanOutcome.CLEAN, ScanOutcome.NOT_CONFIGURED)


@dataclass(frozen=True)
class ScanResult:
    """The outcome of one scan."""

    outcome: ScanOutcome
    # The scanner's own summary, trimmed. Useful to a reviewer and not trusted
    # for anything.
    detail: str = ""

    @property
    def clean(self) -> bool:
        return self.outcome is ScanOutcome.CLEAN


def scan_file(path: str, settings: Settings | None = None) -> ScanResult:
    """Run the configured scanner against a file.

    The command is split with shlex and executed without a shell, so a path
    cannot become part of a command line. The file path is passed as an
    argument, never interpolated into a string.
    """
    settings = settings or get_settings()
    command = settings.malware_scanner_command.strip()

    if not command:
        if settings.environment is Environment.PRODUCTION:
            # Unreachable: the configuration check refuses to start. Kept as a
            # second line, because a security control that exists in only one
            # place is one refactor from being gone.
            return ScanResult(ScanOutcome.FAILED, "no scanner configured in production")
        logger.warning("upload.scan_skipped", reason="no scanner configured")
        return ScanResult(ScanOutcome.NOT_CONFIGURED)

    argv = [*shlex.split(command), path]

    try:
        completed = subprocess.run(  # noqa: S603 - argv list, no shell
            argv,
            capture_output=True,
            timeout=SCAN_TIMEOUT_SECONDS,
            check=False,
            # No environment inheritance beyond what the scanner needs.
            env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
        )
    except FileNotFoundError:
        logger.error("upload.scanner_missing", command=argv[0])
        return ScanResult(ScanOutcome.FAILED, f"scanner not found: {argv[0]}")
    except subprocess.TimeoutExpired:
        logger.error("upload.scan_timeout", seconds=SCAN_TIMEOUT_SECONDS)
        return ScanResult(ScanOutcome.FAILED, "scan timed out")
    except OSError as exc:
        logger.error("upload.scan_error", error=type(exc).__name__)
        return ScanResult(ScanOutcome.FAILED, f"scan failed: {type(exc).__name__}")

    detail = (completed.stdout or b"").decode("utf-8", errors="replace")[:500].strip()

    # ClamAV and most scanners use 0 for clean and 1 for infected. Anything
    # else is an error, and an error is not a clean result.
    if completed.returncode == 0:
        return ScanResult(ScanOutcome.CLEAN, detail)
    if completed.returncode == 1:
        logger.warning("upload.infected")
        return ScanResult(ScanOutcome.INFECTED, detail)

    logger.error("upload.scan_error", returncode=completed.returncode)
    return ScanResult(ScanOutcome.FAILED, f"scanner exited {completed.returncode}: {detail}")
