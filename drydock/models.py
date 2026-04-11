from __future__ import annotations

from datetime import datetime

from .extensions import db

DEFAULT_BACKUP_INTERVAL_HOURS = 24


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)


class SensorLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    temp_1 = db.Column(db.Float, nullable=True)
    hum_1 = db.Column(db.Float, nullable=True)
    temp_2 = db.Column(db.Float, nullable=True)
    hum_2 = db.Column(db.Float, nullable=True)
    raw_adc = db.Column(db.Float, nullable=True)
    rfid_uid = db.Column(db.String(64), nullable=True)


class CalibrationSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tare_offset = db.Column(db.Float, nullable=False, default=0.0)
    calibration_multiplier = db.Column(db.Float, nullable=False, default=1.0)


class AppSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    spoolman_url = db.Column(db.String(255), default="http://localhost:8000")
    humidity_threshold = db.Column(db.Float, default=10.0)
    log_retention_days = db.Column(db.Integer, default=7)
    theme = db.Column(db.String(20), nullable=False, default="dark")
    log_level = db.Column(db.String(20), nullable=False, default="INFO")
    calibration_reminder_days = db.Column(db.Integer, nullable=False, default=30)
    last_calibration_at = db.Column(db.DateTime, nullable=True)
    backup_interval_hours = db.Column(
        db.Integer, nullable=False, default=DEFAULT_BACKUP_INTERVAL_HOURS
    )
    backup_retention_count = db.Column(db.Integer, nullable=False, default=10)
    last_humidity_alert_at = db.Column(db.DateTime, nullable=True)


class SpoolmanSyncLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    rfid_uid = db.Column(db.String(64), nullable=False)
    spoolman_id = db.Column(db.Integer, nullable=False)
    success = db.Column(db.Boolean, nullable=False)
    message = db.Column(db.String(500), nullable=True)


class BackupLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    backup_path = db.Column(db.String(500), nullable=True)
    reason = db.Column(db.String(50), nullable=False, default="manual")
    success = db.Column(db.Boolean, nullable=False, default=True)
    message = db.Column(db.String(500), nullable=True)
