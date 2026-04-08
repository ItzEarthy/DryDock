import csv
import json
import logging
import math
import os
import shutil
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO, StringIO
from pathlib import Path
from statistics import mean

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, Response, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

APP_START_TIME = datetime.utcnow()
EMA_ALPHA = 0.2
AUTO_ZERO_GRAMS = 8.0
AUTO_ZERO_ADJUST_ALPHA = 0.08
DEFAULT_BACKUP_INTERVAL_HOURS = 24
SERVICE_STATUS_TTL_SECONDS = 15

_SERVICE_STATUS_CACHE = {
    "spoolman": {"at": None, "key": None, "value": (False, "Unknown")},
    "db": {"at": None, "value": (False, "Unknown")},
}

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///drydock.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = "drydock_secure_key_123"

db = SQLAlchemy(app)
migrate = Migrate(app, db)


# --- MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")


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
    webhook_url = db.Column(db.String(255), nullable=True)
    theme = db.Column(db.String(20), nullable=False, default="dark")
    log_level = db.Column(db.String(20), nullable=False, default="INFO")
    temp_compensation_factor = db.Column(db.Float, nullable=False, default=0.0)
    temp_reference_c = db.Column(db.Float, nullable=False, default=25.0)
    calibration_reminder_days = db.Column(db.Integer, nullable=False, default=30)
    last_calibration_at = db.Column(db.DateTime, nullable=True)
    backup_interval_hours = db.Column(db.Integer, nullable=False, default=DEFAULT_BACKUP_INTERVAL_HOURS)
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


# --- AUTH HELPERS ---
def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user or user.role != "admin":
            return "<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>Admin permission required.</div>", 403
        return fn(*args, **kwargs)

    return wrapper


@app.context_processor
def inject_user():
    user = get_current_user()
    return {"current_user": user}


@app.before_request
def check_setup():
    path = request.path or "/"
    if path.startswith("/static") or path.startswith("/api/update"):
        return

    public_paths = {"/login", "/setup", "/favicon.ico"}
    has_user = User.query.first() is not None

    if not has_user and path != "/setup":
        return redirect(url_for("setup"))

    if has_user and "user_id" not in session and path not in public_paths:
        return redirect(url_for("login"))


# --- LOGGING ---
class JsonLogFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "level": record.levelname,
            "event": getattr(record, "event_name", record.getMessage()),
            "message": record.getMessage(),
        }
        extra_fields = getattr(record, "event_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        return json.dumps(payload, default=str)


DRYDOCK_LOGGER = logging.getLogger("drydock")


def configure_structured_logging(level_name="INFO"):
    logs_dir = Path(app.root_path) / "instance" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "drydock.jsonl"

    level = getattr(logging, (level_name or "INFO").upper(), logging.INFO)
    DRYDOCK_LOGGER.setLevel(level)

    has_file_handler = False
    for handler in DRYDOCK_LOGGER.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == log_file:
            has_file_handler = True
            break

    if not has_file_handler:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(JsonLogFormatter())
        DRYDOCK_LOGGER.addHandler(file_handler)

    DRYDOCK_LOGGER.propagate = False


def log_event(level, event_name, **event_fields):
    severity = getattr(logging, str(level).upper(), logging.INFO)
    DRYDOCK_LOGGER.log(severity, event_name, extra={"event_name": event_name, "event_fields": event_fields})


# --- UTILS ---
def _to_float(value):
    try:
        parsed = float(value)
        if math.isnan(parsed) or math.isinf(parsed):
            return None
        return parsed
    except (TypeError, ValueError):
        return None


def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_or_create(model):
    obj = model.query.first()
    if not obj:
        obj = model()
        db.session.add(obj)
        db.session.commit()
    return obj


def _table_columns(table_name):
    rows = db.session.execute(text(f"PRAGMA table_info('{table_name}')")).mappings().all()
    return {row["name"] for row in rows}


def ensure_schema_extensions():
    if "sqlite" not in app.config.get("SQLALCHEMY_DATABASE_URI", ""):
        return

    db.create_all()

    user_cols = _table_columns("user")
    if "role" not in user_cols:
        db.session.execute(text("ALTER TABLE user ADD COLUMN role VARCHAR(20) DEFAULT 'user'"))

    app_cols = _table_columns("app_settings")
    app_additions = [
        ("theme", "theme VARCHAR(20) NOT NULL DEFAULT 'dark'"),
        ("log_level", "log_level VARCHAR(20) NOT NULL DEFAULT 'INFO'"),
        ("temp_compensation_factor", "temp_compensation_factor FLOAT NOT NULL DEFAULT 0.0"),
        ("temp_reference_c", "temp_reference_c FLOAT NOT NULL DEFAULT 25.0"),
        ("calibration_reminder_days", "calibration_reminder_days INTEGER NOT NULL DEFAULT 30"),
        ("last_calibration_at", "last_calibration_at DATETIME"),
        ("backup_interval_hours", f"backup_interval_hours INTEGER NOT NULL DEFAULT {DEFAULT_BACKUP_INTERVAL_HOURS}"),
        ("backup_retention_count", "backup_retention_count INTEGER NOT NULL DEFAULT 10"),
        ("last_humidity_alert_at", "last_humidity_alert_at DATETIME"),
    ]

    for col_name, col_ddl in app_additions:
        if col_name not in app_cols:
            db.session.execute(text(f"ALTER TABLE app_settings ADD COLUMN {col_ddl}"))

    db.session.commit()


def ensure_first_admin():
    users = User.query.order_by(User.id.asc()).all()
    if not users:
        return

    admin_exists = any(u.role == "admin" for u in users)
    if admin_exists:
        return

    users[0].role = "admin"
    db.session.commit()


def _db_file_path():
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not uri.startswith("sqlite:///"):
        return None

    raw_path = uri.replace("sqlite:///", "", 1)
    path = Path(raw_path)
    if path.is_absolute():
        return path

    candidate = Path(app.instance_path) / raw_path
    if candidate.exists():
        return candidate
    return Path(app.root_path) / raw_path


def format_uptime(delta):
    total = int(delta.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    return f"{hours}h {minutes}m"


def trigger_webhook(message, severity="info"):
    settings = get_or_create(AppSettings)
    if not settings.webhook_url:
        return False

    try:
        requests.post(
            settings.webhook_url,
            json={"content": f"[{severity.upper()}] {message}"},
            timeout=3,
        )
        return True
    except requests.RequestException:
        return False


def _perform_software_tare():
    latest = SensorLog.query.order_by(SensorLog.timestamp.desc()).first()
    if not latest or latest.raw_adc is None:
        return False, "No sensor data available to tare."

    calibration = get_or_create(CalibrationSettings)
    calibration.tare_offset = latest.raw_adc
    db.session.commit()
    log_event("INFO", "scale_tare", tare_offset=calibration.tare_offset)
    return True, "Scale tared using latest telemetry sample."


def calculate_weight_grams(raw_adc, temp_1, calibration, settings):
    if raw_adc is None:
        return None

    multiplier = calibration.calibration_multiplier if calibration.calibration_multiplier else 1.0
    temp_factor = settings.temp_compensation_factor if settings.temp_compensation_factor is not None else 0.0
    ref_temp = settings.temp_reference_c if settings.temp_reference_c is not None else 25.0
    measured_temp = temp_1 if temp_1 is not None else ref_temp

    drift_adjustment = (measured_temp - ref_temp) * temp_factor
    compensated_raw = raw_adc - calibration.tare_offset - drift_adjustment
    return compensated_raw * multiplier


def compute_weight_stability(logs, calibration, settings):
    weights = []
    for log in logs[-8:]:
        weight = calculate_weight_grams(log.raw_adc, log.temp_1, calibration, settings)
        if weight is not None:
            weights.append(weight)

    if not weights:
        return {
            "progress": 0,
            "stable": False,
            "stable_weight": None,
            "ema_weight": None,
            "samples": 0,
        }

    live_weight = weights[-1]
    if abs(live_weight) <= AUTO_ZERO_GRAMS:
        live_weight = 0.0

    return {
        "progress": 100,
        "stable": True,
        "stable_weight": round(live_weight, 2),
        "ema_weight": round(live_weight, 2),
        "samples": len(weights),
    }


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


def _spoolman_request(path, method="GET", payload=None, timeout=5, base_url=None):
    settings = get_or_create(AppSettings)
    url_base = (base_url or settings.spoolman_url or "").rstrip("/")
    if not url_base:
        raise ValueError("Spoolman URL is not configured")

    payload_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"{url_base}{path}",
        method=method,
        data=payload_bytes,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8").strip()
        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"raw": body}


def _normalize_collection(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ["items", "results", "data", "spools", "filaments"]:
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def check_spoolman(url):
    if not url:
        return False, "Not Configured"

    cache = _SERVICE_STATUS_CACHE["spoolman"]
    now = datetime.utcnow()
    key = (url or "").rstrip("/")
    if (
        cache["at"]
        and cache["key"] == key
        and (now - cache["at"]).total_seconds() < SERVICE_STATUS_TTL_SECONDS
    ):
        return cache["value"]

    try:
        _spoolman_request("/api/v1/info", method="GET", timeout=3, base_url=url)
        result = (True, "Connected")
    except Exception:
        result = (False, "Unreachable")

    cache["at"] = now
    cache["key"] = key
    cache["value"] = result
    return result


def fetch_active_spools(limit=25):
    endpoints = [f"/api/v1/spool?limit={limit}", f"/api/v1/spool"]
    for endpoint in endpoints:
        try:
            payload = _spoolman_request(endpoint)
            spools = _normalize_collection(payload)
            if spools:
                return spools[:limit]
        except Exception:
            continue
    return []


def fetch_filament_options(limit=150):
    endpoints = [f"/api/v1/filament?limit={limit}", "/api/v1/filament"]
    for endpoint in endpoints:
        try:
            payload = _spoolman_request(endpoint)
            filaments = _normalize_collection(payload)
            if filaments:
                return filaments[:limit]
        except Exception:
            continue
    return []


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


def create_database_backup(reason="manual"):
    db_path = _db_file_path()
    if not db_path or not db_path.exists():
        backup = BackupLog(reason=reason, success=False, message="SQLite database file not found")
        db.session.add(backup)
        db.session.commit()
        return False, "Database file not found", None

    backups_dir = Path(app.root_path) / "instance" / "backups"
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
        existing = sorted(backups_dir.glob("drydock_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
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


def build_context(include_spools=True):
    latest_log = SensorLog.query.order_by(SensorLog.timestamp.desc()).first()
    calibration = get_or_create(CalibrationSettings)
    settings = get_or_create(AppSettings)

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

    sensor_status = {"ok": False, "msg": "No Data"}
    if latest_log:
        sensor_age = (datetime.utcnow() - latest_log.timestamp).total_seconds()
        sensor_status = {"ok": sensor_age < 180, "msg": "Online" if sensor_age < 180 else "Offline"}

    spoolman_ok, spoolman_msg = check_spoolman(settings.spoolman_url)
    db_ok, db_msg = check_database_status()
    uptime = format_uptime(datetime.utcnow() - APP_START_TIME)

    last_cal = settings.last_calibration_at
    calibration_due = True
    if last_cal:
        calibration_due = datetime.utcnow() - last_cal >= timedelta(days=max(settings.calibration_reminder_days, 1))

    samples = session.get("calibration_samples", [])
    known_weight = session.get("calibration_known_weight")

    spools = fetch_active_spools() if include_spools else []
    filaments = fetch_filament_options() if include_spools else []

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
        "calibration_due": calibration_due,
        "calibration_samples_count": len(samples),
        "calibration_known_weight": known_weight,
        "active_theme": settings.theme if settings.theme in {"dark", "light"} else "dark",
        "permission_matrix": [
            {"feature": "Dashboard & telemetry", "admin": True, "user": True},
            {"feature": "Run spool workflows", "admin": True, "user": True},
            {"feature": "Save settings", "admin": True, "user": False},
            {"feature": "Calibration + tare", "admin": True, "user": False},
            {"feature": "Import/export config", "admin": True, "user": False},
            {"feature": "Backups", "admin": True, "user": False},
            {"feature": "Firmware builder", "admin": True, "user": False},
        ],
    }


# --- AUTH ROUTES ---
@app.route("/setup", methods=["GET", "POST"])
def setup():
    if User.query.first():
        return redirect(url_for("index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password")
        if username and password:
            user = User(username=username, password_hash=generate_password_hash(password), role="admin")
            db.session.add(user)
            db.session.commit()
            session["user_id"] = user.id
            return redirect(url_for("index"))

    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            return redirect(url_for("index"))
        return "Invalid credentials", 401
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


# --- DASHBOARD ROUTES ---
@app.route("/")
def index():
    return render_template("index.html", **build_context(include_spools=True))


@app.route("/settings_page")
def settings_page():
    return render_template("settings.html", **build_context(include_spools=False))


@app.route("/partials/<section>")
def render_partial(section):
    allowed = {"latest", "calibration", "spool_list"}
    if section not in allowed:
        return "Not found", 404
    include_spools = section == "spool_list"
    return render_template(f"partials/{section}.html", **build_context(include_spools=include_spools))


# --- SENSOR INGEST ---
@app.route("/api/update", methods=["POST"])
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
        temp_1 = _to_float(data.get("temp_1"))
        ref_temp = settings.temp_reference_c if settings.temp_reference_c is not None else 25.0
        temp_factor = settings.temp_compensation_factor if settings.temp_compensation_factor is not None else 0.0
        drift_adjustment = ((temp_1 if temp_1 is not None else ref_temp) - ref_temp) * temp_factor
        raw_adc = (reported_weight / multiplier) + calibration.tare_offset + drift_adjustment

    rfid_uid = str(data.get("rfid_uid")).strip() if data.get("rfid_uid") else None
    if rfid_uid == "":
        rfid_uid = None

    temp_1 = _to_float(data.get("temp_1"))
    hum_1 = _to_float(data.get("hum_1"))
    temp_2 = _to_float(data.get("temp_2"))
    hum_2 = _to_float(data.get("hum_2"))

    # Auto-zero correction: when the scale is effectively empty, slowly adapt tare offset.
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


# --- SETTINGS ---
@app.post("/settings")
@admin_required
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

    temp_comp_factor = _to_float(request.form.get("temp_compensation_factor"))
    if temp_comp_factor is not None:
        settings.temp_compensation_factor = temp_comp_factor

    temp_reference = _to_float(request.form.get("temp_reference_c"))
    if temp_reference is not None:
        settings.temp_reference_c = temp_reference

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


@app.post("/settings/test_spoolman")
def test_spoolman_connection():
    url = (request.form.get("spoolman_url") or get_or_create(AppSettings).spoolman_url or "").strip()
    ok, msg = check_spoolman(url)
    if ok:
        return "<div class='p-3 border border-[#35AB57] text-[#35AB57] rounded text-sm mt-2'>Spoolman test successful.</div>"
    return f"<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm mt-2'>Spoolman test failed: {msg}</div>", 400


@app.get("/settings/export")
@admin_required
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
            "temp_compensation_factor": settings.temp_compensation_factor,
            "temp_reference_c": settings.temp_reference_c,
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


@app.post("/settings/import")
@admin_required
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
        "temp_compensation_factor",
        "temp_reference_c",
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


@app.post("/settings/backup")
@admin_required
def manual_backup():
    success, message, backup_path = create_database_backup(reason="manual")
    if success:
        return f"<div class='p-3 border border-[#35AB57] text-[#35AB57] rounded text-sm'>Backup created: {backup_path.name}</div>"
    return f"<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>Backup failed: {message}</div>", 500


# --- CALIBRATION ---
def render_calibration_card(message=None, is_error=False):
    context = build_context(include_spools=False)
    context["calibration_message"] = message
    context["calibration_error"] = is_error
    return render_template("partials/calibration.html", **context)


@app.post("/calibration/tare")
@admin_required
def auto_tare():
    success, message = _perform_software_tare()
    if not success:
        return render_calibration_card(message=message, is_error=True)
    return render_calibration_card(message=message, is_error=False)


@app.post("/calibration/multiplier")
@admin_required
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
    log_event("INFO", "calibration_single_point", known_weight=known_weight, multiplier=calibration.calibration_multiplier)
    return render_calibration_card(message="Calibration multiplier updated.", is_error=False)


@app.post("/calibration/samples/start")
@admin_required
def start_calibration_samples():
    known_weight = _to_float(request.form.get("known_weight"))
    if not known_weight or known_weight <= 0:
        return render_calibration_card(message="Enter a valid known weight.", is_error=True)

    session["calibration_known_weight"] = known_weight
    session["calibration_samples"] = []
    session.modified = True
    return render_calibration_card(message="Guided sampling started.", is_error=False)


@app.post("/calibration/samples/add")
@admin_required
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


@app.post("/calibration/samples/finish")
@admin_required
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


@app.post("/api/scale/remote_tare")
def remote_tare():
    success, message = _perform_software_tare()
    if request.headers.get("HX-Request"):
        if success:
            return f"<div class='p-2 border border-[#35AB57] text-[#35AB57] rounded text-xs'>{message}</div>"
        return f"<div class='p-2 border border-[#E72A2E] text-[#E72A2E] rounded text-xs'>{message}</div>", 400

    return jsonify({"ok": success, "message": message}), (200 if success else 400)


@app.get("/api/weight/stability")
def weight_stability_api():
    context = build_context(include_spools=False)
    return jsonify(
        {
            "progress": context["stability"]["progress"],
            "stable": context["stability"]["stable"],
            "stable_weight": context["stability"]["stable_weight"],
            "ema_weight": context["stability"]["ema_weight"],
            "samples": context["stability"]["samples"],
        }
    )


@app.get("/api/live_snapshot")
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


# --- SPOOLMAN + FILAMENT ---
@app.post("/spoolman/sync")
def spoolman_sync():
    spoolman_id = (request.form.get("spoolman_id") or "").strip()
    rfid_uid = (request.form.get("rfid_uid") or "").strip()
    weight = _to_float(request.form.get("weight"))

    if not spoolman_id.isdigit() or not rfid_uid:
        return "<div class='text-[#E72A2E] text-sm'>Invalid spool ID or RFID UID.</div>", 400
    if weight is None:
        weight = 0.0

    payload = {"id": int(spoolman_id), "remaining_weight": weight, "extra": {"rfid_uid": rfid_uid}}
    try:
        _spoolman_request(f"/api/v1/spool/{int(spoolman_id)}", method="PATCH", payload=payload)
        db.session.add(
            SpoolmanSyncLog(
                rfid_uid=rfid_uid,
                spoolman_id=int(spoolman_id),
                success=True,
                message=f"Synced with remaining weight {weight}",
            )
        )
        db.session.commit()
        log_event("INFO", "spool_sync", spoolman_id=spoolman_id, rfid_uid=rfid_uid, weight=weight)
        return "<div class='p-3 border border-[#35AB57] text-[#35AB57] rounded text-sm'>Synced successfully.</div>"
    except Exception as exc:
        db.session.add(
            SpoolmanSyncLog(
                rfid_uid=rfid_uid,
                spoolman_id=int(spoolman_id),
                success=False,
                message=str(exc),
            )
        )
        db.session.commit()
        log_event("ERROR", "spool_sync_failed", spoolman_id=spoolman_id, rfid_uid=rfid_uid, error=str(exc))
        return f"<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>Sync failed: {exc}</div>", 400


@app.post("/spoolman/action")
def spoolman_action():
    action = (request.form.get("action") or "").strip().lower()
    spool_id = _to_int(request.form.get("spool_id"))
    if spool_id is None:
        return "<div class='text-[#E72A2E] text-sm'>Spool ID missing.</div>", 400

    try:
        if action == "reweigh":
            weight = _to_float(request.form.get("weight"))
            if weight is None:
                current = build_context(include_spools=False)
                weight = current["stability"]["stable_weight"] or current["weight_grams"] or 0.0
            payload = {"id": spool_id, "remaining_weight": weight}
            _spoolman_request(f"/api/v1/spool/{spool_id}", method="PATCH", payload=payload)
            message = f"Spool {spool_id} re-weighed to {round(weight, 1)}g"
        elif action == "mark_used":
            payload = {"id": spool_id, "remaining_weight": 0}
            _spoolman_request(f"/api/v1/spool/{spool_id}", method="PATCH", payload=payload)
            message = f"Spool {spool_id} marked used"
        elif action == "remove":
            _spoolman_request(f"/api/v1/spool/{spool_id}", method="DELETE")
            message = f"Spool {spool_id} removed"
        else:
            return "<div class='text-[#E72A2E] text-sm'>Unknown action.</div>", 400

        log_event("INFO", "spoolman_action", action=action, spool_id=spool_id)
        return render_template("partials/spool_list.html", action_message=message, **build_context(include_spools=True))
    except Exception as exc:
        return render_template(
            "partials/spool_list.html",
            action_message=f"Action failed: {exc}",
            action_error=True,
            **build_context(include_spools=True),
        )


@app.post("/spoolman/add_filament")
def spoolman_add_filament():
    filament_id = _to_int(request.form.get("filament_id"))
    rfid_uid = (request.form.get("rfid_uid") or "").strip()
    remaining_weight = _to_float(request.form.get("remaining_weight"))

    if filament_id is None or not rfid_uid:
        return "<div class='text-[#E72A2E] text-sm'>Filament selection and RFID UID are required.</div>", 400
    if remaining_weight is None:
        remaining_weight = 0.0

    payload = {
        "filament_id": filament_id,
        "remaining_weight": remaining_weight,
        "extra": {"rfid_uid": rfid_uid},
    }

    try:
        _spoolman_request("/api/v1/spool", method="POST", payload=payload)
        log_event("INFO", "spool_added", filament_id=filament_id, rfid_uid=rfid_uid, remaining_weight=remaining_weight)
        return "<div class='p-3 border border-[#35AB57] text-[#35AB57] rounded text-sm'>New filament spool created and linked to RFID.</div>"
    except Exception as exc:
        return f"<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>Failed to create spool: {exc}</div>", 400


@app.get("/wizard/modal")
def wizard_modal():
    return render_template("partials/filament_wizard.html", **build_context(include_spools=True))


@app.route("/wizard/step/<step_name>", methods=["GET", "POST"])
def wizard_step(step_name):
    context = build_context(include_spools=True)

    # Auto-detect spool matching latest scanned RFID (if any)
    selected_spool_id = None
    latest_uid = (context.get("latest_uid") or "").strip()
    if latest_uid:
        for spool in context.get("spoolman_spools", []):
            # spool is a dict parsed from Spoolman JSON; check 'extra' then top-level rfid fields
            spool_extra = spool.get("extra") if isinstance(spool, dict) else getattr(spool, "extra", None)
            spool_rfid = None
            if isinstance(spool_extra, dict):
                spool_rfid = (spool_extra.get("rfid_uid") or spool_extra.get("rfid") or "").strip()
            if not spool_rfid:
                spool_rfid = (spool.get("rfid_uid") if isinstance(spool, dict) else getattr(spool, "rfid_uid", None)) or ""
                spool_rfid = spool_rfid.strip() if spool_rfid else ""
            if spool_rfid and spool_rfid == latest_uid:
                spool_id_val = (spool.get("id") if isinstance(spool, dict) else getattr(spool, "id", None)) or (spool.get("spool_id") if isinstance(spool, dict) else getattr(spool, "spool_id", None))
                try:
                    selected_spool_id = int(spool_id_val)
                except Exception:
                    selected_spool_id = spool_id_val
                break
    context["selected_spool_id"] = selected_spool_id

    if step_name == "clear_scan":
        if request.method == "POST":
            success, message = _perform_software_tare()
            context["wizard_message"] = message
            context["wizard_error"] = not success
            if not success:
                return render_template("partials/wizard_clear_scan.html", **context), 400
            return render_template("partials/wizard_add_spool.html", **context)
        return render_template("partials/wizard_clear_scan.html", **context)

    if step_name == "add_spool":
        return render_template("partials/wizard_add_spool.html", **context)

    if step_name == "harden":
        sw = request.args.get("selected_weight")
        if sw:
            try:
                context["selected_weight"] = float(sw)
            except Exception:
                context["selected_weight"] = context["stability"]["stable_weight"] or context["weight_grams"] or 0
        else:
            context["selected_weight"] = context["stability"]["stable_weight"] or context["weight_grams"] or 0
        return render_template("partials/wizard_confirm.html", **context)

    if step_name == "harden_status":
        sw = request.args.get("selected_weight")
        if sw:
            try:
                context["selected_weight"] = float(sw)
            except Exception:
                context["selected_weight"] = context["stability"]["stable_weight"] or context["weight_grams"] or 0
        else:
            context["selected_weight"] = context["stability"]["stable_weight"] or context["weight_grams"] or 0
        return render_template("partials/wizard_confirm.html", **context)

    if step_name == "confirm":
        sw = request.args.get("selected_weight")
        if sw:
            try:
                context["selected_weight"] = float(sw)
            except Exception:
                context["selected_weight"] = context["stability"]["stable_weight"] or context["weight_grams"] or 0
        else:
            context["selected_weight"] = context["stability"]["stable_weight"] or context["weight_grams"] or 0
        return render_template("partials/wizard_confirm.html", **context)

    return "Unknown wizard step", 404


@app.post("/wizard/step/accept")
def wizard_accept():
    spool_id = _to_int(request.form.get("spoolman_id"))
    rfid_uid = (request.form.get("rfid_uid") or "").strip()
    weight = _to_float(request.form.get("weight"))
    if spool_id is None or not rfid_uid:
        return "<div class='text-[#E72A2E] text-sm'>Spool ID and RFID UID are required.</div>", 400
    if weight is None:
        weight = 0.0

    payload = {"id": spool_id, "remaining_weight": weight, "extra": {"rfid_uid": rfid_uid}}
    try:
        _spoolman_request(f"/api/v1/spool/{spool_id}", method="PATCH", payload=payload)
        return "<div class='p-3 border border-[#35AB57] text-[#35AB57] rounded text-sm'>Wizard complete: spool updated in Spoolman.</div>"
    except Exception as exc:
        return f"<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>Wizard sync failed: {exc}</div>", 400


# --- HISTORY / EXPORT ---
@app.route("/api/history")
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
    logs = SensorLog.query.filter(SensorLog.timestamp >= since).order_by(SensorLog.timestamp.asc()).all()

    history = build_history(logs, aggregation, hours, settings, calibration)
    history["range"] = range_name
    history["aggregation"] = aggregation
    return jsonify(history)


@app.route("/api/system/health")
def get_system_health():
    context = build_context(include_spools=False)
    return jsonify(
        {
            "uptime": context["uptime"],
            "esp32": context["sensor_status"],
            "spoolman": context["spoolman_status"],
            "database": context["db_status"],
        }
    )


@app.route("/api/logs/download")
def download_logs():
    fmt = (request.args.get("format") or "csv").lower()
    hours = _to_int(request.args.get("hours"), 168)
    since = datetime.utcnow() - timedelta(hours=max(hours, 1))

    logs = SensorLog.query.filter(SensorLog.timestamp >= since).order_by(SensorLog.timestamp.asc()).all()
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
                "weight_grams": calculate_weight_grams(item.raw_adc, item.temp_1, calibration, settings),
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
    writer.writerow(["Timestamp", "Temp_1", "Hum_1", "Temp_2", "Hum_2", "Raw_ADC", "RFID_UID", "Weight_grams"])
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


@app.route("/api/logs/structured/download")
def download_structured_logs():
    log_path = Path(app.root_path) / "instance" / "logs" / "drydock.jsonl"
    if not log_path.exists():
        return "No structured log file exists yet.", 404
    return send_file(log_path, as_attachment=True, download_name="drydock_events.jsonl", mimetype="application/json")


# --- FIRMWARE BUILDER ---
def _escape_cpp_string(value):
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def generate_esp32_firmware(ssid, password, server_url):
    template = r'''#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <Adafruit_AM2320.h>
#include <Adafruit_NAU7802.h>

// -------- Injected at build time --------
const char* WIFI_SSID = "__WIFI_SSID__";
const char* WIFI_PASSWORD = "__WIFI_PASSWORD__";
const char* FLASK_UPDATE_URL = "__SERVER_URL__";

// -------- Pin Layout --------
#define RST_PIN 1
#define SS_PIN  10
#define SCK_PIN 12
#define MISO_PIN 13
#define MOSI_PIN 11

#define I2C1_SDA 4
#define I2C1_SCL 5
#define I2C2_SDA 8
#define I2C2_SCL 9

// -------- Weight Filtering / Hardening --------
float emaWeight = 0.0;
const float EMA_ALPHA = 0.2;

float finalStableWeight = 0.0;
unsigned long lastWeightChangeTime = 0;
const float SETTLE_THRESHOLD = 3.0;
const unsigned long SETTLE_DELAY_MS = 4000;

float calibrationFactor = 426.75;
int32_t zeroOffset = 0;
int32_t latestRawAdc = 0;

MFRC522* mfrc522;
Adafruit_AM2320* am2320_1;
Adafruit_AM2320* am2320_2;
Adafruit_NAU7802* nau;

unsigned long lastSensorRead = 0;
unsigned long lastPostMs = 0;

bool rfidFound = false;
bool am1Found = false;
bool am2Found = false;
bool nauFound = false;

String lastRfidUid = "";

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long started = millis();

  while (WiFi.status() != WL_CONNECTED && millis() - started < 12000) {
    delay(250);
  }
}

String readRfidUid() {
  if (!rfidFound) {
    return "";
  }

  if (!mfrc522->PICC_IsNewCardPresent() || !mfrc522->PICC_ReadCardSerial()) {
    return "";
  }

  String uid = "";
  for (byte i = 0; i < mfrc522->uid.size; i++) {
    if (mfrc522->uid.uidByte[i] < 0x10) {
      uid += "0";
    }
    uid += String(mfrc522->uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  mfrc522->PICC_HaltA();
  mfrc522->PCD_StopCrypto1();
  return uid;
}

void tareScale() {
  if (!nauFound) {
    return;
  }

  int32_t tareSum = 0;
  for (int i = 0; i < 10; i++) {
    while (!nau->available()) {
      delay(1);
    }
    tareSum += nau->read();
  }
  zeroOffset = tareSum / 10;
  emaWeight = 0.0;
  finalStableWeight = 0.0;
  lastWeightChangeTime = millis();
}

void readWeightFilter() {
  if (!nauFound) {
    return;
  }
  if (millis() - lastSensorRead < 100) {
    return;
  }

  lastSensorRead = millis();
  if (!nau->available()) {
    return;
  }

  int32_t currentReading = nau->read();
  latestRawAdc = currentReading;
  float rawWeight = (currentReading - zeroOffset) / calibrationFactor;

  if (fabs(rawWeight - emaWeight) > 50.0) {
    emaWeight = rawWeight;
  } else {
    emaWeight = (EMA_ALPHA * rawWeight) + ((1.0 - EMA_ALPHA) * emaWeight);
  }

  if (fabs(emaWeight - finalStableWeight) > SETTLE_THRESHOLD) {
    finalStableWeight = emaWeight;
    lastWeightChangeTime = millis();
  }
}

int hardeningProgress() {
  unsigned long elapsed = millis() - lastWeightChangeTime;
  if (elapsed >= SETTLE_DELAY_MS) {
    return 100;
  }
  return (int)((elapsed * 100UL) / SETTLE_DELAY_MS);
}

void postTelemetry(float temp1, float hum1, float temp2, float hum2) {
  connectWiFi();
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  HTTPClient http;
  http.begin(FLASK_UPDATE_URL);
  http.addHeader("Content-Type", "application/json");

  String payload = "{";
  payload += "\"temp_1\":" + String(temp1, 2) + ",";
  payload += "\"hum_1\":" + String(hum1, 2) + ",";
  payload += "\"temp_2\":" + String(temp2, 2) + ",";
  payload += "\"hum_2\":" + String(hum2, 2) + ",";
  payload += "\"raw_adc\":" + String(latestRawAdc) + ",";
  payload += "\"weight\":" + String(finalStableWeight, 2) + ",";
  payload += "\"hardening_progress\":" + String(hardeningProgress()) + ",";
  payload += "\"rfid_uid\":\"" + lastRfidUid + "\"";
  payload += "}";

  http.POST(payload);
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(250);

  Wire.begin(I2C1_SDA, I2C1_SCL);
  Wire1.begin(I2C2_SDA, I2C2_SCL);
  SPI.begin(SCK_PIN, MISO_PIN, MOSI_PIN, SS_PIN);

  mfrc522 = new MFRC522(SS_PIN, RST_PIN);
  am2320_1 = new Adafruit_AM2320(&Wire);
  am2320_2 = new Adafruit_AM2320(&Wire1);
  nau = new Adafruit_NAU7802();

  mfrc522->PCD_Init();
  byte rfidVersion = mfrc522->PCD_ReadRegister(mfrc522->VersionReg);
  rfidFound = (rfidVersion != 0x00 && rfidVersion != 0xFF);

  am1Found = am2320_1->begin();
  am2Found = am2320_2->begin();

  if (nau->begin(&Wire)) {
    nauFound = true;
    nau->setLDO(NAU7802_3V3);
    nau->setGain(NAU7802_GAIN_128);
    nau->setRate(NAU7802_RATE_10SPS);
    nau->calibrate(NAU7802_CALMOD_INTERNAL);
    nau->calibrate(NAU7802_CALMOD_OFFSET);
    delay(1000);
    tareScale();
  }

  connectWiFi();
  lastWeightChangeTime = millis();
}

void loop() {
  readWeightFilter();

  String scanned = readRfidUid();
  if (scanned.length() > 0) {
    lastRfidUid = scanned;
  }

    if (millis() - lastPostMs >= 5000) {
    lastPostMs = millis();

    float temp1 = am1Found ? am2320_1->readTemperature() : NAN;
    float hum1 = am1Found ? am2320_1->readHumidity() : NAN;
    float temp2 = am2Found ? am2320_2->readTemperature() : NAN;
    float hum2 = am2Found ? am2320_2->readHumidity() : NAN;

    if (isnan(temp1)) temp1 = 0;
    if (isnan(hum1)) hum1 = 0;
    if (isnan(temp2)) temp2 = 0;
    if (isnan(hum2)) hum2 = 0;

    postTelemetry(temp1, hum1, temp2, hum2);
  }

  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();

    if (cmd == "TARE") {
      tareScale();
      Serial.println("{\"status\":\"tared\"}");
    } else if (cmd == "WEIGHT") {
      Serial.print("{\"weight\":");
      Serial.print(finalStableWeight, 2);
      Serial.println("}");
    } else if (cmd == "ENV") {
      float temp1 = am1Found ? am2320_1->readTemperature() : 0;
      float hum1 = am1Found ? am2320_1->readHumidity() : 0;
      Serial.print("{\"temp\":");
      Serial.print(temp1, 2);
      Serial.print(",\"hum\":");
      Serial.print(hum1, 2);
      Serial.println("}");
    }
  }
}
'''

    return (
        template.replace("__WIFI_SSID__", _escape_cpp_string(ssid))
        .replace("__WIFI_PASSWORD__", _escape_cpp_string(password))
        .replace("__SERVER_URL__", _escape_cpp_string(server_url))
    )


@app.route("/build_firmware", methods=["POST"])
@admin_required
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

    log_event("INFO", "firmware_generated", server_url=server_url, generated_by=get_current_user().username)
    return send_file(
        buffer,
        as_attachment=True,
        download_name="DryDock.ino",
        mimetype="text/plain",
    )


# --- BACKGROUND TASKS ---
def prune_old_logs():
    with app.app_context():
        settings = get_or_create(AppSettings)
        if settings.log_retention_days <= 0:
            return
        cutoff = datetime.utcnow() - timedelta(days=settings.log_retention_days)
        deleted = SensorLog.query.filter(SensorLog.timestamp < cutoff).delete()
        db.session.commit()
        if deleted:
            log_event("INFO", "logs_pruned", deleted_rows=deleted, retention_days=settings.log_retention_days)


def monitor_humidity_thresholds():
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
        if trigger_webhook(message, severity="warn"):
            settings.last_humidity_alert_at = datetime.utcnow()
            db.session.commit()
            log_event("INFO", "humidity_alert_sent", delta=hum_delta, threshold=settings.humidity_threshold)


def run_scheduled_backups():
    with app.app_context():
        settings = get_or_create(AppSettings)
        latest = BackupLog.query.filter_by(success=True).order_by(BackupLog.timestamp.desc()).first()
        due = True
        if latest:
            due = datetime.utcnow() - latest.timestamp >= timedelta(hours=max(settings.backup_interval_hours, 1))
        if due:
            create_database_backup(reason="scheduled")


scheduler = BackgroundScheduler()


def start_scheduler():
    if scheduler.running:
        return

    scheduler.add_job(func=prune_old_logs, trigger="interval", hours=24, id="prune_old_logs", replace_existing=True)
    scheduler.add_job(
        func=monitor_humidity_thresholds,
        trigger="interval",
        minutes=2,
        id="monitor_humidity_thresholds",
        replace_existing=True,
    )
    scheduler.add_job(
        func=run_scheduled_backups,
        trigger="interval",
        minutes=30,
        id="run_scheduled_backups",
        replace_existing=True,
    )
    scheduler.start()


with app.app_context():
    ensure_schema_extensions()
    ensure_first_admin()
    configure_structured_logging(get_or_create(AppSettings).log_level)


if __name__ == "__main__":
    debug_mode = True
    if not debug_mode or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_scheduler()
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)