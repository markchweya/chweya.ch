"""Whether the database schema matches the code.

Every migration the code needs and the database lacks surfaces as a 500 on
the first page that touches the new column, with a traceback that says
"column does not exist" and nothing about why. This check runs at startup
and says the one useful thing: run the migrations.
"""

from __future__ import annotations

from dataclasses import dataclass

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class SchemaLag:
    """The database is at ``current`` while the code expects ``head``."""

    current: str | None
    head: str


def schema_lag(engine: Engine, ini_path: str = "alembic.ini") -> SchemaLag | None:
    """Return what the database is missing, or None when it is up to date."""
    head = ScriptDirectory.from_config(Config(ini_path)).get_current_head()
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    if head is None or current == head:
        return None
    return SchemaLag(current=current, head=head)
