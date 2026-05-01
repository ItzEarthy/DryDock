from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from pathlib import Path
from statistics import mean

from flask import Blueprint, Response, current_app, jsonify, request, send_file
from sqlalchemy import func, text, literal_column

from ..extensions import db
from ..models import AppSettings, CalibrationSettings, SensorLog
from ..utils.database import check_database_status, get_or_create
from ..utils.logging import APP_START_TIME, format_uptime, log_event
from ..utils.scale import AUTO_ZERO_ADJUST_ALPHA, AUTO_ZERO_GRAMS, _to_float, _to_int, calculate_weight_grams, compute_weight_stability
from ..utils.spoolman import check_spoolman


api_bp = Blueprint("api", __name__)


def _select_aggregate(values, mode):
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    if mode == "min":
        return min(clean)
    if mode == "max":
        return max(clean)
    return mean(clean)


def _history_bucket_seconds(hours, aggregation):
    if aggregation == "raw":
        return 0
    if hours <= 1:
        return 60
    if hours <= 24:
        return 300
    return 3600


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _utc_iso(dt: datetime) -> str:
    return _as_utc(dt).isoformat().replace("+00:00", "Z")


def _utc_ms(dt: datetime) -> int:
    return int(_as_utc(dt).timestamp() * 1000)


def _history_gap_threshold_seconds(hours, aggregation):
    bucket_seconds = _history_bucket_seconds(hours, aggregation)
    if bucket_seconds:
        return max(bucket_seconds * 3, 15 * 60)
    return 15 * 60


def _build_history_payload(points, aggregation, hours, settings, calibration):
    gap_threshold_ms = _history_gap_threshold_seconds(hours, aggregation) * 1000
    labels = []
    hum_1 = []
    hum_2 = []
    temp_1 = []
    temp_2 = []
    weight = []
    anomalies = []
    series = {
        "hum_1": [],
        "hum_2": [],
        "temp_1": [],
        "temp_2": [],
        "weight": [],
        "anomalies": [],
    }

    previous_ms = None
    for point in points:
        ts = point["timestamp"] if isinstance(point, dict) else point.timestamp
        ts_ms = _utc_ms(ts)

        if previous_ms is not None and ts_ms - previous_ms > gap_threshold_ms:
            gap_ms = previous_ms + ((ts_ms - previous_ms) // 2)
            separator = {"x": gap_ms, "y": None}
            for name in ("hum_1", "hum_2", "temp_1", "temp_2", "weight"):
                series[name].append(separator.copy())

        labels.append(_utc_iso(ts))

        h1 = point["hum_1"] if isinstance(point, dict) else point.hum_1
        h2 = point["hum_2"] if isinstance(point, dict) else point.hum_2
        t1 = point["temp_1"] if isinstance(point, dict) else point.temp_1
        t2 = point["temp_2"] if isinstance(point, dict) else point.temp_2
        raw_adc = point["raw_adc"] if isinstance(point, dict) else point.raw_adc

        hum_1.append(h1)
        hum_2.append(h2)
        temp_1.append(t1)
        temp_2.append(t2)
        weight_value = calculate_weight_grams(raw_adc, t1, calibration, settings)
        weight.append(weight_value)

        series["hum_1"].append({"x": ts_ms, "y": h1})
        series["hum_2"].append({"x": ts_ms, "y": h2})
        series["temp_1"].append({"x": ts_ms, "y": t1})
        series["temp_2"].append({"x": ts_ms, "y": t2})
        series["weight"].append({"x": ts_ms, "y": weight_value})

        if h1 is not None:
            if h1 > settings.humidity_threshold:
                anomaly = {"x": ts_ms, "y": h1}
                anomalies.append(anomaly)
                series["anomalies"].append(anomaly)

        previous_ms = ts_ms

    return {
        "labels": labels,
        "hum_1": hum_1,
        "hum_2": hum_2,
        "temp_1": temp_1,
        "temp_2": temp_2,
        "weight": weight,
        "anomalies": anomalies,
        "series": series,
        "threshold": settings.humidity_threshold,
    }


@api_bp.route("/api/update", methods=["POST"])
def update_data():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data"}), 400

    calibration = get_or_create(CalibrationSettings)
    settings = get_or_create(AppSettings)

    raw_adc = _to_float(data.get("raw_adc"))
    reported_weight = _to_float(data.get("weight"))
    if raw_adc is None and reported_weight is not None:
        multiplier = calibration.calibration_multiplier if calibration.calibration_multiplier else 1.0
        # No temperature compensation: compute raw_adc purely from reported weight and multiplier.
        raw_adc = (reported_weight / multiplier) + calibration.tare_offset

    rfid_uid = str(data.get("rfid_uid")).strip() if data.get("rfid_uid") else None
    if rfid_uid == "":
        rfid_uid = None

    temp_1 = _to_float(data.get("temp_1"))
    hum_1 = _to_float(data.get("hum_1"))
    temp_2 = _to_float(data.get("temp_2"))
    hum_2 = _to_float(data.get("hum_2"))

    if raw_adc is not None:
        current_weight = calculate_weight_grams(raw_adc, temp_1, calibration, settings)
        if current_weight is not None and abs(current_weight) <= AUTO_ZERO_GRAMS:
            calibration.tare_offset = (
                ((1.0 - AUTO_ZERO_ADJUST_ALPHA) * calibration.tare_offset)
                + (AUTO_ZERO_ADJUST_ALPHA * raw_adc)
            )

    db.session.add(
        SensorLog(
            temp_1=temp_1,
            hum_1=hum_1,
            temp_2=temp_2,
            hum_2=hum_2,
            raw_adc=raw_adc,
            rfid_uid=rfid_uid,
        )
    )
    db.session.commit()

    log_event(
        "DEBUG",
        "sensor_update",
        temp_1=_to_float(data.get("temp_1")),
        hum_1=_to_float(data.get("hum_1")),
        temp_2=_to_float(data.get("temp_2")),
        hum_2=_to_float(data.get("hum_2")),
        raw_adc=raw_adc,
        rfid_uid=rfid_uid,
    )
    return jsonify({"status": "success"}), 201


@api_bp.post("/api/scale/remote_tare")
def remote_tare():
    from .dashboard import _perform_software_tare

    success, message = _perform_software_tare()
    if request.headers.get("HX-Request"):
        if success:
            return f"<div class='p-2 border border-[#35AB57] text-[#35AB57] rounded text-xs'>{message}</div>"
        return f"<div class='p-2 border border-[#E72A2E] text-[#E72A2E] rounded text-xs'>{message}</div>", 400

    return jsonify({"ok": success, "message": message}), (200 if success else 400)


@api_bp.get("/api/weight/stability")
def weight_stability_api():
    calibration = get_or_create(CalibrationSettings)
    settings = get_or_create(AppSettings)

    recent_logs = SensorLog.query.order_by(SensorLog.timestamp.desc()).limit(8).all()
    recent_logs.reverse()

    stability = compute_weight_stability(recent_logs, calibration, settings)

    return jsonify(
        {
            "progress": stability["progress"],
            "stable": stability["stable"],
            "stable_weight": stability["stable_weight"],
            "ema_weight": stability["ema_weight"],
            "samples": stability["samples"],
        }
    )

@api_bp.get("/api/live_snapshot")
def live_snapshot_api():
    latest = SensorLog.query.order_by(SensorLog.timestamp.desc()).first()
    calibration = get_or_create(CalibrationSettings)
    settings = get_or_create(AppSettings)
    latest_uid_row = (
        SensorLog.query.filter(SensorLog.rfid_uid.isnot(None), SensorLog.rfid_uid != "")
        .order_by(SensorLog.timestamp.desc())
        .first()
    )

    if not latest:
        return jsonify({"ok": False, "timestamp": None})

    sensor_age = (datetime.utcnow() - latest.timestamp).total_seconds()
    esp_ok = sensor_age < 180

    weight = calculate_weight_grams(latest.raw_adc, latest.temp_1, calibration, settings)
    if weight is None or abs(weight) <= AUTO_ZERO_GRAMS:
        weight = 0.0

    hours_remaining = None
    if esp_ok and latest.hum_1 is not None:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        oldest_in_window = SensorLog.query.filter(
            SensorLog.timestamp >= cutoff, 
            SensorLog.hum_1.isnot(None)
        ).order_by(SensorLog.timestamp.asc()).first()
        
        if oldest_in_window:
            time_delta_hours = (latest.timestamp - oldest_in_window.timestamp).total_seconds() / 3600.0
            if time_delta_hours >= 2.0:
                hum_delta = latest.hum_1 - oldest_in_window.hum_1
                rate_per_hour = hum_delta / time_delta_hours
                # Use a lower threshold for sensitivity to slower humidity climbs.
                if rate_per_hour > 0.01:
                    hours_remaining = (settings.humidity_threshold - latest.hum_1) / rate_per_hour

    return jsonify(
        {
            "ok": bool(esp_ok),
            "weight_grams": round(weight, 2) if esp_ok else None,
            "raw_adc": latest.raw_adc if esp_ok else None,
            "tare_offset": round(calibration.tare_offset, 3),
            "rfid_uid": latest_uid_row.rfid_uid if latest_uid_row else "",
            "timestamp": _utc_iso(latest.timestamp),
            # NEW FIELD FOR FRONTEND:
            "hours_remaining": round(hours_remaining, 1) if hours_remaining and hours_remaining > 0 else None,
        }
    )


@api_bp.route("/api/history")
def get_history():
    range_name = (request.args.get("range") or "24h").lower()
    aggregation = (request.args.get("aggregation") or "avg").lower()
    if aggregation not in {"raw", "avg", "min", "max"}:
        aggregation = "avg"

    range_map = {"1h": 1, "24h": 24, "7d": 168}
    hours = range_map.get(range_name)
    if hours is None:
        hours = _to_int(request.args.get("hours"), 24)

    settings = get_or_create(AppSettings)
    calibration = get_or_create(CalibrationSettings)
    since = datetime.utcnow() - timedelta(hours=max(hours, 1))

    bucket_seconds = _history_bucket_seconds(hours, aggregation)
    if bucket_seconds and aggregation in {"avg", "min", "max"}:
        bucket_expr = literal_column(
            f"(CAST(strftime('%s', timestamp) AS INTEGER) / {int(bucket_seconds)}) * {int(bucket_seconds)}"
        )

        agg_map = {"avg": func.avg, "min": func.min, "max": func.max}
        agg_fn = agg_map.get(aggregation, func.avg)

        bucketed_rows = (
            db.session.query(
                bucket_expr.label("bucket"),
                agg_fn(SensorLog.temp_1).label("temp_1"),
                agg_fn(SensorLog.temp_2).label("temp_2"),
                agg_fn(SensorLog.hum_1).label("hum_1"),
                agg_fn(SensorLog.hum_2).label("hum_2"),
                agg_fn(SensorLog.raw_adc).label("raw_adc"),
            )
            .filter(SensorLog.timestamp >= since)
            .group_by(bucket_expr)
            .order_by(bucket_expr.asc())
            .all()
        )

        rows = []
        for row in bucketed_rows:
            ts = datetime.fromtimestamp(int(row.bucket), tz=timezone.utc)
            rows.append(
                {
                    "timestamp": ts,
                    "hum_1": row.hum_1,
                    "hum_2": row.hum_2,
                    "temp_1": row.temp_1,
                    "temp_2": row.temp_2,
                    "raw_adc": row.raw_adc,
                }
            )

        history = _build_history_payload(rows, aggregation, hours, settings, calibration)
    else:
        logs = (
            SensorLog.query.filter(SensorLog.timestamp >= since)
            .order_by(SensorLog.timestamp.asc())
            .all()
        )
        history = _build_history_payload(logs, aggregation, hours, settings, calibration)

    history["range"] = range_name
    history["aggregation"] = aggregation
    return jsonify(history)


@api_bp.route("/api/system/health")
def get_system_health():
    # Mirror the existing payload structure.
    settings = get_or_create(AppSettings)
    spoolman_ok, spoolman_msg = check_spoolman(settings.spoolman_url)
    db_ok, db_msg = check_database_status()
    uptime = "Unknown"
    try:
        if APP_START_TIME:
            uptime = format_uptime(datetime.utcnow() - APP_START_TIME)
    except Exception:
        uptime = "Unknown"

    from .dashboard import _sensor_status

    settings = get_or_create(AppSettings)
    installed_version = getattr(settings, 'installed_version', '') or ''

    return jsonify(
        {
            "uptime": uptime,
            "esp32": _sensor_status(),
            "spoolman": {"ok": spoolman_ok, "msg": spoolman_msg},
            "database": {"ok": db_ok, "msg": db_msg},
            "installed_version": installed_version,
        }
    )


@api_bp.route("/api/system/install_version", methods=["POST"])
def set_installed_version():
    settings = get_or_create(AppSettings)
    payload = request.get_json() or {}
    ver = payload.get("version") or ""
    settings.installed_version = ver
    from ..extensions import db as _db
    try:
        _db.session.add(settings)
        _db.session.commit()
        return jsonify({"ok": True, "installed_version": settings.installed_version})
    except Exception as exc:
        # Log minimal server-side info and return a safe message to client
        try:
            log_event("ERROR", "save_installed_version_failed", error=str(exc))
        except Exception:
            pass
        _db.session.rollback()
        return (
            jsonify({"ok": False, "error": "Failed to save installed version on server."}),
            500,
        )


@api_bp.route("/api/logs/download")
def download_logs():
    fmt = (request.args.get("format") or "csv").lower()
    hours = _to_int(request.args.get("hours"), 168)
    since = datetime.utcnow() - timedelta(hours=max(hours, 1))

    logs = (
        SensorLog.query.filter(SensorLog.timestamp >= since)
        .order_by(SensorLog.timestamp.asc())
        .all()
    )
    calibration = get_or_create(CalibrationSettings)
    settings = get_or_create(AppSettings)

    rows = []
    for item in logs:
        rows.append(
            {
                "timestamp": item.timestamp.isoformat(),
                "temp_1": item.temp_1,
                "hum_1": item.hum_1,
                "temp_2": item.temp_2,
                "hum_2": item.hum_2,
                "raw_adc": item.raw_adc,
                "rfid_uid": item.rfid_uid,
                "weight_grams": calculate_weight_grams(
                    item.raw_adc, item.temp_1, calibration, settings
                ),
            }
        )

    if fmt == "json":
        output = json.dumps(rows, indent=2).encode("utf-8")
        return send_file(
            BytesIO(output),
            as_attachment=True,
            download_name="drydock_logs.json",
            mimetype="application/json",
        )

    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(
        [
            "Timestamp",
            "Temp_1",
            "Hum_1",
            "Temp_2",
            "Hum_2",
            "Raw_ADC",
            "RFID_UID",
            "Weight_grams",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["timestamp"],
                row["temp_1"],
                row["hum_1"],
                row["temp_2"],
                row["hum_2"],
                row["raw_adc"],
                row["rfid_uid"],
                row["weight_grams"],
            ]
        )

    return Response(
        csv_buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=drydock_logs.csv"},
    )


@api_bp.route("/api/logs/structured/download")
def download_structured_logs():
    log_path = Path(current_app.root_path) / "instance" / "logs" / "drydock.jsonl"
    if not log_path.exists():
        return "No structured log file exists yet.", 404
    return send_file(
        log_path,
        as_attachment=True,
        download_name="drydock_events.jsonl",
        mimetype="application/json",
    )
