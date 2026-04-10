from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
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


def build_history(logs, aggregation, hours, settings, calibration):
    bucket_seconds = _history_bucket_seconds(hours, aggregation)
    buckets = {}

    for log in logs:
        if bucket_seconds:
            epoch = int(log.timestamp.timestamp())
            key = epoch - (epoch % bucket_seconds)
        else:
            key = f"{int(log.timestamp.timestamp() * 1000)}-{log.id}"

        if key not in buckets:
            buckets[key] = {
                "timestamp": log.timestamp,
                "temp_1": [],
                "temp_2": [],
                "hum_1": [],
                "hum_2": [],
                "weight": [],
            }

        row = buckets[key]
        row["temp_1"].append(log.temp_1)
        row["temp_2"].append(log.temp_2)
        row["hum_1"].append(log.hum_1)
        row["hum_2"].append(log.hum_2)
        row["weight"].append(calculate_weight_grams(log.raw_adc, log.temp_1, calibration, settings))

    ordered_keys = sorted(buckets.keys())
    labels, hum_1, hum_2, temp_1, temp_2, weight = [], [], [], [], [], []
    anomalies = []

    agg_mode = "avg" if aggregation == "raw" else aggregation
    for key in ordered_keys:
        point = buckets[key]
        ts = point["timestamp"]
        labels.append(ts.isoformat())
        h1 = _select_aggregate(point["hum_1"], agg_mode)
        h2 = _select_aggregate(point["hum_2"], agg_mode)
        t1 = _select_aggregate(point["temp_1"], agg_mode)
        t2 = _select_aggregate(point["temp_2"], agg_mode)
        w = _select_aggregate(point["weight"], agg_mode)

        hum_1.append(h1)
        hum_2.append(h2)
        temp_1.append(t1)
        temp_2.append(t2)
        weight.append(w)

        if h1 is not None and h2 is not None:
            delta = h2 - h1
            if delta < settings.humidity_threshold:
                anomalies.append({"x": ts.isoformat(), "y": delta})

    return {
        "labels": labels,
        "hum_1": hum_1,
        "hum_2": hum_2,
        "temp_1": temp_1,
        "temp_2": temp_2,
        "weight": weight,
        "anomalies": anomalies,
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
        return jsonify(
            {
                "ok": False,
                "weight_grams": 0.0,
                "raw_adc": None,
                "tare_offset": calibration.tare_offset,
                "rfid_uid": latest_uid_row.rfid_uid if latest_uid_row else "",
                "timestamp": None,
            }
        )

    weight = calculate_weight_grams(latest.raw_adc, latest.temp_1, calibration, settings)
    if weight is None:
        weight = 0.0
    if abs(weight) <= AUTO_ZERO_GRAMS:
        weight = 0.0

    return jsonify(
        {
            "ok": True,
            "weight_grams": round(weight, 2),
            "raw_adc": latest.raw_adc,
            "tare_offset": round(calibration.tare_offset, 3),
            "rfid_uid": latest_uid_row.rfid_uid if latest_uid_row else "",
            "timestamp": latest.timestamp.isoformat(),
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

        rows = (
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

        labels, hum_1, hum_2, temp_1, temp_2, weight, anomalies = [], [], [], [], [], [], []
        for row in rows:
            ts = datetime.utcfromtimestamp(int(row.bucket))
            labels.append(ts.isoformat())

            h1 = row.hum_1
            h2 = row.hum_2
            t1 = row.temp_1
            t2 = row.temp_2
            raw_adc = row.raw_adc

            hum_1.append(h1)
            hum_2.append(h2)
            temp_1.append(t1)
            temp_2.append(t2)
            weight.append(calculate_weight_grams(raw_adc, t1, calibration, settings))

            if h1 is not None and h2 is not None:
                delta = h2 - h1
                if delta < settings.humidity_threshold:
                    anomalies.append({"x": ts.isoformat(), "y": delta})

        history = {
            "labels": labels,
            "hum_1": hum_1,
            "hum_2": hum_2,
            "temp_1": temp_1,
            "temp_2": temp_2,
            "weight": weight,
            "anomalies": anomalies,
            "threshold": settings.humidity_threshold,
        }
    else:
        logs = (
            SensorLog.query.filter(SensorLog.timestamp >= since)
            .order_by(SensorLog.timestamp.asc())
            .all()
        )
        history = build_history(logs, aggregation, hours, settings, calibration)

    history["range"] = range_name
    history["aggregation"] = aggregation
    return jsonify(history)


@api_bp.route("/api/system/health")
def get_system_health():
    # Mirror the existing payload structure.
    settings = get_or_create(AppSettings)
    spoolman_ok, spoolman_msg = check_spoolman(settings.spoolman_url)
    db_ok, db_msg = check_database_status()
    uptime = format_uptime(datetime.utcnow() - APP_START_TIME)

    from .dashboard import _sensor_status

    return jsonify(
        {
            "uptime": uptime,
            "esp32": _sensor_status(),
            "spoolman": {"ok": spoolman_ok, "msg": spoolman_msg},
            "database": {"ok": db_ok, "msg": db_msg},
        }
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
