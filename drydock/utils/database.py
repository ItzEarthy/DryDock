from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from flask import current_app, g
from sqlalchemy import text

from ..extensions import db
from ..models import (
    AppSettings,
    BackupLog,
    CalibrationSettings,
    DEFAULT_BACKUP_INTERVAL_HOURS,
    SensorLog,
    User,
)
from .logging import log_event

SERVICE_STATUS_TTL_SECONDS = 15

_SERVICE_STATUS_CACHE = {
    "spoolman": {"at": None, "key": None, "value": (False, "Unknown")},
    "db": {"at": None, "value": (False, "Unknown")},
}


def get_or_create(model):
    cache_key = f"_cached_{model.__name__}"
    if hasattr(g, cache_key):
        return getattr(g, cache_key)

    obj = model.query.first()
    if not obj:
        obj = model()
        db.session.add(obj)
        db.session.commit()

    setattr(g, cache_key, obj)
    return obj


def _table_columns(table_name: str) -> set[str]:
    rows = db.session.execute(text(f"PRAGMA table_info('{table_name}')")).mappings().all()
    return {row["name"] for row in rows}


def ensure_schema_extensions() -> None:
    if "sqlite" not in current_app.config.get("SQLALCHEMY_DATABASE_URI", ""):
        return

    db.create_all()

    # Enable WAL mode for concurrent SQLite reads and writes
    db.session.execute(text("PRAGMA journal_mode=WAL;"))

    user_cols = _table_columns("user")
    if "role" not in user_cols:
        db.session.execute(
            text("ALTER TABLE user ADD COLUMN role VARCHAR(20) DEFAULT 'user'")
        )

    app_cols = _table_columns("app_settings")
    app_additions = [
        ("theme", "theme VARCHAR(20) NOT NULL DEFAULT 'dark'"),
        ("log_level", "log_level VARCHAR(20) NOT NULL DEFAULT 'INFO'"),
        (
            "temp_compensation_factor",
            "temp_compensation_factor FLOAT NOT NULL DEFAULT 0.0",
        ),
        ("temp_reference_c", "temp_reference_c FLOAT NOT NULL DEFAULT 25.0"),
        (
            "calibration_reminder_days",
            "calibration_reminder_days INTEGER NOT NULL DEFAULT 30",
        ),
        ("last_calibration_at", "last_calibration_at DATETIME"),
        (
            "backup_interval_hours",
            f"backup_interval_hours INTEGER NOT NULL DEFAULT {DEFAULT_BACKUP_INTERVAL_HOURS}",
        ),
        ("backup_retention_count", "backup_retention_count INTEGER NOT NULL DEFAULT 10"),
        ("last_humidity_alert_at", "last_humidity_alert_at DATETIME"),
    ]

    for col_name, col_ddl in app_additions:
        if col_name not in app_cols:
            db.session.execute(text(f"ALTER TABLE app_settings ADD COLUMN {col_ddl}"))

    # SQLite performance: ensure indexes on hot SensorLog query patterns.
    try:
        db.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_sensor_log_timestamp ON sensor_log(timestamp)"
            )
        )
        db.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_sensor_log_rfid_uid ON sensor_log(rfid_uid)"
            )
        )
        db.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_sensor_log_rfid_uid_timestamp ON sensor_log(rfid_uid, timestamp)"
            )
        )
    except Exception:
        pass

    db.session.commit()


def ensure_first_admin() -> None:
    users = User.query.order_by(User.id.asc()).all()
    if not users:
        return

    admin_exists = any(u.role == "admin" for u in users)
    if admin_exists:
        return

    users[0].role = "admin"
    db.session.commit()


def _db_file_path():
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not uri.startswith("sqlite:///"):
        return None

    raw_path = uri.replace("sqlite:///", "", 1)
    path = Path(raw_path)
    if path.is_absolute():
        return path

    candidate = Path(current_app.instance_path) / raw_path
    if candidate.exists():
        return candidate
    return Path(current_app.root_path) / raw_path


def check_database_status():
    cache = _SERVICE_STATUS_CACHE["db"]
    now = datetime.utcnow()
    if cache["at"] and (now - cache["at"]).total_seconds() < SERVICE_STATUS_TTL_SECONDS:
        return cache["value"]

    try:
        db.session.execute(text("SELECT 1"))
        result = (True, "Online")
    except Exception:
        result = (False, "Unavailable")

    cache["at"] = now
    cache["value"] = result
    return result


def create_database_backup(reason: str = "manual"):
    db_path = _db_file_path()
    if not db_path or not db_path.exists():
        backup = BackupLog(reason=reason, success=False, message="SQLite database file not found")
        db.session.add(backup)
        db.session.commit()
        return False, "Database file not found", None

    backups_dir = Path(current_app.root_path) / "instance" / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_path = backups_dir / f"drydock_{stamp}.db"

    try:
        db.session.commit()
        shutil.copy2(db_path, backup_path)
        backup_row = BackupLog(reason=reason, success=True, backup_path=str(backup_path), message="Backup created")
        db.session.add(backup_row)

        settings = get_or_create(AppSettings)
        keep_count = settings.backup_retention_count or 10
        existing = sorted(
            backups_dir.glob("drydock_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in existing[keep_count:]:
            old.unlink(missing_ok=True)

        db.session.commit()
        log_event("INFO", "db_backup_created", reason=reason, backup_path=str(backup_path))
        return True, "Backup created", backup_path
    except Exception as exc:
        backup_row = BackupLog(reason=reason, success=False, message=str(exc))
        db.session.add(backup_row)
        db.session.commit()
        log_event("ERROR", "db_backup_failed", reason=reason, error=str(exc))
        return False, str(exc), None
