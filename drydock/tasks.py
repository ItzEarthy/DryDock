from __future__ import annotations

from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from .models import AppSettings, BackupLog, SensorLog
from .utils.database import create_database_backup, get_or_create
from .utils.logging import log_event


def prune_old_logs(app):
    with app.app_context():
        settings = get_or_create(AppSettings)
        if settings.log_retention_days <= 0:
            return
        cutoff = datetime.utcnow() - timedelta(days=settings.log_retention_days)
        deleted = SensorLog.query.filter(SensorLog.timestamp < cutoff).delete()
        from .extensions import db

        db.session.commit()
        if deleted:
            log_event(
                "INFO",
                "logs_pruned",
                deleted_rows=deleted,
                retention_days=settings.log_retention_days,
            )


def monitor_humidity_thresholds(app):
    with app.app_context():
        settings = get_or_create(AppSettings)
        latest = SensorLog.query.order_by(SensorLog.timestamp.desc()).first()
        if not latest or latest.hum_1 is None or latest.hum_2 is None:
            return

        hum_delta = latest.hum_2 - latest.hum_1
        if hum_delta >= settings.humidity_threshold:
            return

        recent_alert = settings.last_humidity_alert_at
        if recent_alert and (datetime.utcnow() - recent_alert) < timedelta(minutes=30):
            return

        message = (
            f"DryDock humidity alert: delta={hum_delta:.2f}% is below threshold "
            f"{settings.humidity_threshold:.2f}%"
        )
        settings.last_humidity_alert_at = datetime.utcnow()
        from .extensions import db

        db.session.commit()
        log_event(
            "INFO",
            "humidity_alert_triggered",
            delta=hum_delta,
            threshold=settings.humidity_threshold,
        )


def run_scheduled_backups(app):
    with app.app_context():
        settings = get_or_create(AppSettings)
        latest = BackupLog.query.filter_by(success=True).order_by(BackupLog.timestamp.desc()).first()
        due = True
        if latest:
            due = datetime.utcnow() - latest.timestamp >= timedelta(
                hours=max(settings.backup_interval_hours, 1)
            )
        if due:
            create_database_backup(reason="scheduled")


scheduler = BackgroundScheduler()


def start_scheduler(app):
    if scheduler.running:
        return

    scheduler.add_job(
        func=lambda: prune_old_logs(app),
        trigger="interval",
        hours=24,
        id="prune_old_logs",
        replace_existing=True,
    )
    scheduler.add_job(
        func=lambda: monitor_humidity_thresholds(app),
        trigger="interval",
        minutes=2,
        id="monitor_humidity_thresholds",
        replace_existing=True,
    )
    scheduler.add_job(
        func=lambda: run_scheduled_backups(app),
        trigger="interval",
        minutes=30,
        id="run_scheduled_backups",
        replace_existing=True,
    )
    scheduler.start()
