"""SQLAlchemy ORM models.

Every model is imported here so that Alembic autogenerate and
``Base.metadata`` see the complete schema. Adding a model file without adding
it to this list silently drops those tables from migrations.
"""

from app.db.models.audit import GENESIS_HASH, AuditAction, AuditEvent, AuditOutcome
from app.db.models.system import SettingKey, SystemSetting, get_setting, set_setting
from app.db.models.user import ROLE_DESCRIPTIONS, Role, RoleName, User, UserRole, UserSession

__all__ = [
    "GENESIS_HASH",
    "ROLE_DESCRIPTIONS",
    "AuditAction",
    "AuditEvent",
    "AuditOutcome",
    "Role",
    "RoleName",
    "SettingKey",
    "SystemSetting",
    "User",
    "UserRole",
    "UserSession",
    "get_setting",
    "set_setting",
]
