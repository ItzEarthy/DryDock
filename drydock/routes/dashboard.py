from __future__ import annotations

import json
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from statistics import mean

from flask import Blueprint, jsonify, render_template, request, send_file, session

from ..extensions import db
from ..models import (
    AppSettings,
    CalibrationSettings,
    SensorLog,
    
)
from ..utils.database import create_database_backup, get_or_create
from ..utils.firmware import generate_esp32_firmware
from ..utils.logging import APP_START_TIME, configure_structured_logging, format_uptime, log_event
from ..utils.scale import AUTO_ZERO_GRAMS, _to_float, _to_int, calculate_weight_grams, compute_weight_stability
from ..utils.spoolman import (
    _spoolman_request,
    check_spoolman,
    fetch_active_spools,
    fetch_filament_options,
)
from .auth import get_current_user, login_required


dashboard_bp = Blueprint("dashboard", __name__)


def _sensor_status():
    latest_log = SensorLog.query.order_by(SensorLog.timestamp.desc()).first()
    status = {"ok": False, "msg": "No Data"}
    if latest_log:
        sensor_age = (datetime.utcnow() - latest_log.timestamp).total_seconds()
        status = {
            "ok": sensor_age < 180,
            "msg": "Online" if sensor_age < 180 else "Offline",
        }
    return status


def _perform_software_tare():
    latest = SensorLog.query.order_by(SensorLog.timestamp.desc()).first()
    if not latest or latest.raw_adc is None:
        return False, "No sensor data available to tare."

    calibration = get_or_create(CalibrationSettings)
    calibration.tare_offset = latest.raw_adc
    db.session.commit()
    log_event("INFO", "scale_tare", tare_offset=calibration.tare_offset)
    return True, "Scale tared using latest telemetry sample."


def build_context(include_spools=True):
    calibration = get_or_create(CalibrationSettings)
    settings = get_or_create(AppSettings)

    # Determine whether ESP32 telemetry is currently online. If offline, avoid exposing
    # live telemetry in the UI (prevents stale values from being shown or acted upon).
    sensor_status = _sensor_status()
    if sensor_status.get("ok"):
        latest_log = SensorLog.query.order_by(SensorLog.timestamp.desc()).first()
        uid_log = (
            SensorLog.query.filter(SensorLog.rfid_uid.isnot(None), SensorLog.rfid_uid != "")
            .order_by(SensorLog.timestamp.desc())
            .first()
        )

        recent_logs = SensorLog.query.order_by(SensorLog.timestamp.desc()).limit(180).all()
        recent_logs.reverse()
        stability = compute_weight_stability(recent_logs, calibration, settings)

        hum_delta = None
        desiccant_healthy = None
        weight_grams = None
        if latest_log:
            if latest_log.hum_1 is not None and latest_log.hum_2 is not None:
                hum_delta = latest_log.hum_2 - latest_log.hum_1
                desiccant_healthy = hum_delta >= settings.humidity_threshold
            weight_grams = calculate_weight_grams(latest_log.raw_adc, latest_log.temp_1, calibration, settings)
    else:
        # ESP32 is offline: hide live telemetry and related UI values
        latest_log = None
        uid_log = None
        recent_logs = []
        stability = {"progress": 0, "stable": False, "stable_weight": None, "ema_weight": None, "samples": 0}
        hum_delta = None
        desiccant_healthy = None
        weight_grams = None

    # Determine service statuses
    from ..utils.database import check_database_status
    from ..utils.spoolman import check_spoolman

    spoolman_ok, spoolman_msg = check_spoolman(settings.spoolman_url)

    db_ok, db_msg = check_database_status()
    uptime = format_uptime(datetime.utcnow() - APP_START_TIME)

    last_cal = settings.last_calibration_at
    calibration_due = True
    if last_cal:
        calibration_due = datetime.utcnow() - last_cal >= timedelta(
            days=max(settings.calibration_reminder_days, 1)
        )

    samples = session.get("calibration_samples", [])
    known_weight = session.get("calibration_known_weight")

    # Only fetch Spoolman lists when Spoolman is reachable
    spools = fetch_active_spools() if include_spools and spoolman_ok else []
    filaments = fetch_filament_options() if include_spools and spoolman_ok else []

    return {
        "log": latest_log,
        "cal_settings": calibration,
        "app_settings": settings,
        "latest_uid": uid_log.rfid_uid if uid_log else "",
        "hum_delta": hum_delta,
        "weight_grams": weight_grams,
        "weight_kg": (weight_grams / 1000.0) if weight_grams is not None else None,
        "desiccant_healthy": desiccant_healthy,
        "stability": stability,
        "sensor_status": sensor_status,
        "spoolman_status": {"ok": spoolman_ok, "msg": spoolman_msg},
        "db_status": {"ok": db_ok, "msg": db_msg},
        "uptime": uptime,
        "spoolman_spools": spools,
        "filament_options": filaments,
        "spoolman_connected": bool(spoolman_ok),
        "sensor_connected": sensor_status.get("ok", False),
        "calibration_due": calibration_due,
        "calibration_samples_count": len(samples),
        "calibration_known_weight": known_weight,
        "active_theme": settings.theme if settings.theme in {"dark", "light"} else "dark",
    }


@dashboard_bp.route("/")
def index():
    return render_template("index.html", **build_context(include_spools=False))


@dashboard_bp.route("/settings_page")
def settings_page():
    return render_template("settings.html", **build_context(include_spools=False))


@dashboard_bp.route("/partials/<section>")
def render_partial(section):
    allowed = {"latest", "calibration"}
    if section not in allowed:
        return "Not found", 404
    ctx = build_context(include_spools=False)
    return render_template(f"partials/{section}.html", **ctx)


@dashboard_bp.post("/settings")
@login_required
def save_settings():
    settings = get_or_create(AppSettings)

    settings.spoolman_url = (request.form.get("spoolman_url") or "").strip()
    settings.webhook_url = (request.form.get("webhook_url") or "").strip()

    humidity_threshold = _to_float(request.form.get("humidity_threshold"))
    if humidity_threshold is not None:
        settings.humidity_threshold = humidity_threshold

    log_retention_days = _to_int(request.form.get("log_retention_days"))
    if log_retention_days is not None and log_retention_days >= 1:
        settings.log_retention_days = log_retention_days

    # temperature compensation removed

    calibration_reminder_days = _to_int(request.form.get("calibration_reminder_days"))
    if calibration_reminder_days is not None and calibration_reminder_days >= 1:
        settings.calibration_reminder_days = calibration_reminder_days

    backup_interval = _to_int(request.form.get("backup_interval_hours"))
    if backup_interval is not None and backup_interval >= 1:
        settings.backup_interval_hours = backup_interval

    backup_retention = _to_int(request.form.get("backup_retention_count"))
    if backup_retention is not None and backup_retention >= 1:
        settings.backup_retention_count = backup_retention

    theme = (request.form.get("theme") or "dark").lower()
    settings.theme = "light" if theme == "light" else "dark"

    log_level = (request.form.get("log_level") or "INFO").upper()
    settings.log_level = "DEBUG" if log_level == "DEBUG" else "INFO"

    db.session.commit()
    configure_structured_logging(settings.log_level)
    log_event("INFO", "settings_updated", by_user=get_current_user().username)

    return "<div class='p-3 bg-[#35AB57]/20 border border-[#35AB57] text-[#35AB57] rounded mt-4'>Settings saved successfully.</div>"


@dashboard_bp.post("/settings/test_spoolman")
def test_spoolman_connection():
    url = (request.form.get("spoolman_url") or get_or_create(AppSettings).spoolman_url or "").strip()
    ok, msg = check_spoolman(url)
    if ok:
        return "<div class='p-3 border border-[#35AB57] text-[#35AB57] rounded text-sm mt-2'>Spoolman test successful.</div>"
    return (
        f"<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm mt-2'>Spoolman test failed: {msg}</div>",
        400,
    )


@dashboard_bp.get("/settings/export")
@login_required
def export_settings():
    settings = get_or_create(AppSettings)
    calibration = get_or_create(CalibrationSettings)

    payload = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "app_settings": {
            "spoolman_url": settings.spoolman_url,
            "humidity_threshold": settings.humidity_threshold,
            "log_retention_days": settings.log_retention_days,
            "webhook_url": settings.webhook_url,
            "theme": settings.theme,
            "log_level": settings.log_level,
            "calibration_reminder_days": settings.calibration_reminder_days,
            "backup_interval_hours": settings.backup_interval_hours,
            "backup_retention_count": settings.backup_retention_count,
            "last_calibration_at": settings.last_calibration_at.isoformat() if settings.last_calibration_at else None,
        },
        "calibration": {
            "tare_offset": calibration.tare_offset,
            "calibration_multiplier": calibration.calibration_multiplier,
        },
    }

    content = json.dumps(payload, indent=2).encode("utf-8")
    return send_file(
        BytesIO(content),
        as_attachment=True,
        download_name="drydock_config.json",
        mimetype="application/json",
    )


@dashboard_bp.post("/settings/import")
@login_required
def import_settings():
    upload = request.files.get("config_file")
    if not upload:
        return "<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>Please upload a JSON file.</div>", 400

    try:
        payload = json.load(upload)
    except Exception:
        return "<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>Invalid JSON file.</div>", 400

    settings_payload = payload.get("app_settings") or {}
    calibration_payload = payload.get("calibration") or {}

    settings = get_or_create(AppSettings)
    calibration = get_or_create(CalibrationSettings)

    allowed_settings = [
        "spoolman_url",
        "humidity_threshold",
        "log_retention_days",
        "webhook_url",
        "theme",
        "log_level",
        "calibration_reminder_days",
        "backup_interval_hours",
        "backup_retention_count",
    ]
    for key in allowed_settings:
        if key in settings_payload:
            setattr(settings, key, settings_payload[key])

    if "tare_offset" in calibration_payload:
        calibration.tare_offset = _to_float(calibration_payload.get("tare_offset")) or calibration.tare_offset
    if "calibration_multiplier" in calibration_payload:
        calibration.calibration_multiplier = _to_float(calibration_payload.get("calibration_multiplier")) or calibration.calibration_multiplier

    db.session.commit()
    configure_structured_logging(settings.log_level)
    log_event("INFO", "settings_imported", by_user=get_current_user().username)
    return "<div class='p-3 border border-[#35AB57] text-[#35AB57] rounded text-sm'>Configuration imported.</div>"


@dashboard_bp.post("/settings/backup")
@login_required
def manual_backup():
    success, message, backup_path = create_database_backup(reason="manual")
    if success:
        return f"<div class='p-3 border border-[#35AB57] text-[#35AB57] rounded text-sm'>Backup created: {backup_path.name}</div>"
    return f"<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>Backup failed: {message}</div>", 500


def render_calibration_card(message=None, is_error=False):
    context = build_context(include_spools=False)
    context["calibration_message"] = message
    context["calibration_error"] = is_error
    return render_template("partials/calibration.html", **context)


@dashboard_bp.post("/calibration/tare")
@login_required
def auto_tare():
    success, message = _perform_software_tare()
    if not success:
        return render_calibration_card(message=message, is_error=True)
    return render_calibration_card(message=message, is_error=False)


@dashboard_bp.post("/calibration/multiplier")
@login_required
def auto_calibrate_single():
    known_weight = _to_float(request.form.get("known_weight"))
    latest = SensorLog.query.order_by(SensorLog.timestamp.desc()).first()
    if not known_weight or not latest or latest.raw_adc is None:
        return render_calibration_card(message="Invalid input or missing sensor data.", is_error=True)

    calibration = get_or_create(CalibrationSettings)
    diff = latest.raw_adc - calibration.tare_offset
    if diff == 0:
        return render_calibration_card(message="Scale unchanged since tare.", is_error=True)

    calibration.calibration_multiplier = known_weight / diff
    get_or_create(AppSettings).last_calibration_at = datetime.utcnow()
    db.session.commit()
    log_event(
        "INFO",
        "calibration_single_point",
        known_weight=known_weight,
        multiplier=calibration.calibration_multiplier,
    )
    return render_calibration_card(message="Calibration multiplier updated.", is_error=False)


@dashboard_bp.post("/calibration/samples/start")
@login_required
def start_calibration_samples():
    known_weight = _to_float(request.form.get("known_weight"))
    if not known_weight or known_weight <= 0:
        return render_calibration_card(message="Enter a valid known weight.", is_error=True)

    session["calibration_known_weight"] = known_weight
    session["calibration_samples"] = []
    session.modified = True
    return render_calibration_card(message="Guided sampling started.", is_error=False)


@dashboard_bp.post("/calibration/samples/add")
@login_required
def add_calibration_sample():
    samples = session.get("calibration_samples", [])
    if len(samples) >= 20:
        return render_calibration_card(message="Maximum sample count reached (20).", is_error=False)

    latest = SensorLog.query.order_by(SensorLog.timestamp.desc()).first()
    if not latest or latest.raw_adc is None:
        return render_calibration_card(message="No sensor sample available.", is_error=True)

    samples.append(latest.raw_adc)
    session["calibration_samples"] = samples
    session.modified = True
    return render_calibration_card(message=f"Captured sample {len(samples)}.", is_error=False)


@dashboard_bp.post("/calibration/samples/finish")
@login_required
def finish_calibration_samples():
    samples = session.get("calibration_samples", [])
    known_weight = _to_float(session.get("calibration_known_weight"))

    if known_weight is None or len(samples) < 10:
        return render_calibration_card(message="Capture at least 10 samples first.", is_error=True)

    calibration = get_or_create(CalibrationSettings)
    average_raw = mean(samples)
    diff = average_raw - calibration.tare_offset
    if diff == 0:
        return render_calibration_card(message="Sample set matches tare offset.", is_error=True)

    calibration.calibration_multiplier = known_weight / diff
    settings = get_or_create(AppSettings)
    settings.last_calibration_at = datetime.utcnow()
    db.session.commit()

    session.pop("calibration_samples", None)
    session.pop("calibration_known_weight", None)
    session.modified = True

    log_event(
        "INFO",
        "calibration_guided_complete",
        known_weight=known_weight,
        samples=len(samples),
        avg_raw=average_raw,
        multiplier=calibration.calibration_multiplier,
    )
    return render_calibration_card(message="Guided calibration complete.", is_error=False)





@dashboard_bp.route("/build_firmware", methods=["POST"])
@login_required
def build_firmware():
    ssid = request.form.get("ssid", "")
    password = request.form.get("password", "")
    server_ip = request.form.get("pi_ip", "").strip()
    server_port = request.form.get("pi_port", "5000").strip()
    if not ssid or not password or not server_ip:
        return "Missing SSID, password, or server IP", 400

    server_url = f"http://{server_ip}:{server_port}/api/update"
    firmware = generate_esp32_firmware(ssid, password, server_url)

    buffer = BytesIO()
    buffer.write(firmware.encode("utf-8"))
    buffer.seek(0)

    log_event(
        "INFO",
        "firmware_generated",
        server_url=server_url,
        generated_by=get_current_user().username,
    )
    return send_file(
        buffer,
        as_attachment=True,
        download_name="DryDock.ino",
        mimetype="text/plain",
    )


__all__ = ["dashboard_bp"]
