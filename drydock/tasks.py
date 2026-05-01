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
        
        
        cutoff = datetime.utcnow() - timedelta(hours=24)
        from .models import SensorLog
        recent_logs = SensorLog.query.filter(
            SensorLog.timestamp >= cutoff, 
            SensorLog.hum_1.isnot(None)
        ).order_by(SensorLog.timestamp.asc()).all()

        if not recent_logs or len(recent_logs) < 10:
            return  

        latest = recent_logs[-1]
        first = recent_logs[0]

        
        recent_alert = settings.last_humidity_alert_at
        if recent_alert and (datetime.utcnow() - recent_alert) < timedelta(hours=12):
            return

        from .extensions import db
        
        if latest.hum_1 >= settings.humidity_threshold:
            settings.last_humidity_alert_at = datetime.utcnow()
            db.session.commit()
            log_event(
                "WARNING",
                "humidity_critical_alert",
                current_hum=latest.hum_1,
                threshold=settings.humidity_threshold,
                message="Drybox humidity has breached the safe threshold!"
            )
            return

        time_delta_hours = (latest.timestamp - first.timestamp).total_seconds() / 3600.0
        if time_delta_hours < 2.0:
            return

        hum_delta = latest.hum_1 - first.hum_1
        rate_per_hour = hum_delta / time_delta_hours

        # More sensitive predictive trigger: act on smaller upward trends.
        if rate_per_hour > 0.01:
            hours_remaining = (settings.humidity_threshold - latest.hum_1) / rate_per_hour

            if hours_remaining <= settings.predictive_warning_hours:
                settings.last_humidity_alert_at = datetime.utcnow()
                db.session.commit()
                log_event(
                    "INFO",
                    "silica_degradation_warning",
                    current_hum=latest.hum_1,
                    rate_per_hour=rate_per_hour,
                    predicted_hours_left=round(hours_remaining, 1),
                    message=f"Silica degrading. Predicted to breach {settings.humidity_threshold}% in {int(hours_remaining)} hours."
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
