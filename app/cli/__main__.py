"""Dispatcher for ``python -m app.cli``."""

from __future__ import annotations

import sys

COMMANDS = {
    "bootstrap-admin": "Create the first administrator account.",
    "verify-audit": "Walk the audit log and confirm its hash chain is intact.",
    "check-config": "Validate configuration and report what production would refuse.",
    "evaluate": "Run the evaluation suite, including the adversarial cases.",
}


def _usage() -> int:
    print("Usage: python -m app.cli <command> [options]\n")
    print("Commands:")
    width = max(len(name) for name in COMMANDS)
    for name, description in COMMANDS.items():
        print(f"  {name.ljust(width)}  {description}")
    return 1


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        return _usage()

    command, argv = sys.argv[1], sys.argv[2:]

    if command == "bootstrap-admin":
        from app.cli.bootstrap_admin import main as run

        return run(argv)

    if command == "verify-audit":
        from app.cli.verify_audit import main as run

        return run(argv)

    if command == "check-config":
        from app.cli.check_config import main as run

        return run(argv)

    if command == "evaluate":
        from app.cli.evaluate import main as run

        return run(argv)

    print(f"Unknown command: {command}\n", file=sys.stderr)
    return _usage()


if __name__ == "__main__":
    raise SystemExit(main())
