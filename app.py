import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///drydock.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

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
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class AppSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    spoolman_url = db.Column(db.String(255), nullable=True, default="http://localhost:8000")
    humidity_threshold = db.Column(db.Float, nullable=False, default=10.0)

class SpoolmanSyncLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    rfid_uid = db.Column(db.String(64), nullable=False)
    spoolman_id = db.Column(db.Integer, nullable=False)
    success = db.Column(db.Boolean, nullable=False)
    message = db.Column(db.String(500), nullable=True)

def _to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def get_calibration_settings():
    settings = CalibrationSettings.query.first()
    if settings is None:
        settings = CalibrationSettings()
        db.session.add(settings)
        db.session.commit()
    return settings

def get_app_settings():
    settings = AppSettings.query.first()
    if settings is None:
        settings = AppSettings()
        db.session.add(settings)
        db.session.commit()
    return settings

def latest_log():
    return SensorLog.query.order_by(SensorLog.timestamp.desc()).first()

def latest_scanned_uid():
    log = SensorLog.query.filter(SensorLog.rfid_uid.isnot(None), SensorLog.rfid_uid != "").order_by(SensorLog.timestamp.desc()).first()
    return log.rfid_uid if log else ""

def check_spoolman(url):
    if not url: return False, "Not Configured"
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/api/v1/info", method="GET")
        with urllib.request.urlopen(req, timeout=2) as response:
            if response.getcode() == 200: return True, "Connected"
    except Exception: pass
    return False, "Unreachable"

def build_dashboard_context():
    log = latest_log()
    cal_settings = get_calibration_settings()
    app_settings = get_app_settings()

    hum_delta = weight_grams = desiccant_healthy = None
    sensor_status = {"ok": False, "msg": "No Data"}

    if log:
        if (datetime.utcnow() - log.timestamp).total_seconds() < 300:
            sensor_status = {"ok": True, "msg": "Online"}
        else:
            sensor_status = {"ok": False, "msg": "Offline (Stale Data)"}

        if log.hum_1 is not None and log.hum_2 is not None:
            hum_delta = log.hum_2 - log.hum_1
            desiccant_healthy = hum_delta >= app_settings.humidity_threshold
        if log.raw_adc is not None:
            weight_grams = (log.raw_adc - cal_settings.tare_offset) * cal_settings.calibration_multiplier

    spoolman_ok, spoolman_msg = check_spoolman(app_settings.spoolman_url)

    return {
        "log": log,
        "cal_settings": cal_settings,
        "app_settings": app_settings,
        "hum_delta": hum_delta,
        "desiccant_healthy": desiccant_healthy,
        "weight_grams": weight_grams,
        "latest_uid": latest_scanned_uid(),
        "sensor_status": sensor_status,
        "spoolman_status": {"ok": spoolman_ok, "msg": spoolman_msg}
    }

def sync_uid_to_spoolman(spoolman_id, rfid_uid):
    base_url = get_app_settings().spoolman_url.rstrip("/")
    if not base_url: return False, "SPOOLMAN_URL is not configured."
    endpoint = f"{base_url}/api/v1/spool/{spoolman_id}"
    payload = {"id": int(spoolman_id), "extra": {"rfid_uid": rfid_uid, "source": "DryDock"}}
    body = json.dumps(payload).encode("utf-8")

    for method in ("PATCH", "PUT"):
        req = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                if 200 <= response.getcode() < 300: return True, f"Synced UID to Spool {spoolman_id}."
        except urllib.error.HTTPError as e:
            if e.code == 405: continue
            return False, f"HTTP Error {e.code}"
        except Exception as e:
            return False, "Connection Error"
    return False, "Unsupported method."

@app.route("/")
def index():
    return render_template("index.html", **build_dashboard_context())

@app.route("/settings_page")
def settings_page():
    return render_template("settings.html", **build_dashboard_context())

@app.route("/partials/<section>")
def render_partial(section):
    return render_template(f"partials/{section}.html", **build_dashboard_context())

@app.route("/api/update", methods=["POST"])
def update_data():
    data = request.get_json(silent=True)
    if not data: return jsonify({"error": "No data"}), 400
    new_log = SensorLog(
        temp_1=_to_float(data.get("temp_1")), hum_1=_to_float(data.get("hum_1")),
        temp_2=_to_float(data.get("temp_2")), hum_2=_to_float(data.get("hum_2")),
        raw_adc=_to_float(data.get("raw_adc")),
        rfid_uid=(str(data.get("rfid_uid")).strip() if data.get("rfid_uid") else None)
    )
    db.session.add(new_log)
    db.session.commit()
    return jsonify({"status": "success"}), 201

@app.post("/settings")
def save_settings():
    app_settings = get_app_settings()
    app_settings.spoolman_url = request.form.get("spoolman_url", "").strip()
    threshold = _to_float(request.form.get("humidity_threshold"))
    if threshold is not None: app_settings.humidity_threshold = threshold
    db.session.commit()
    return "<div class='p-3 bg-[#35AB57]/20 border border-[#35AB57] text-[#35AB57] rounded mt-4'>Settings Saved Successfully</div>"

@app.post("/calibration/tare")
def auto_tare():
    log = latest_log()
    if not log or log.raw_adc is None: return "<div class='text-[#E72A2E] text-sm mt-2'>No data</div>", 400
    settings = get_calibration_settings()
    settings.tare_offset = log.raw_adc
    db.session.commit()
    return render_template("partials/calibration.html", **build_dashboard_context())

@app.post("/calibration/multiplier")
def auto_calibrate():
    known = _to_float(request.form.get("known_weight"))
    log = latest_log()
    if not known or not log or log.raw_adc is None: return "<div class='text-[#E72A2E] text-sm mt-2'>Invalid Input</div>", 400
    settings = get_calibration_settings()
    adc_diff = log.raw_adc - settings.tare_offset
    if adc_diff == 0: return "<div class='text-[#E72A2E] text-sm mt-2'>Scale unchanged</div>", 400
    settings.calibration_multiplier = known / adc_diff
    db.session.commit()
    return render_template("partials/calibration.html", **build_dashboard_context())

@app.post("/spoolman/sync")
def spoolman_sync():
    s_id = request.form.get("spoolman_id", "").strip()
    uid = request.form.get("rfid_uid", "").strip() or latest_scanned_uid()
    if not s_id.isdigit() or not uid: return "<div class='text-[#E72A2E] text-sm mt-2'>Invalid ID or missing UID.</div>", 400
    success, msg = sync_uid_to_spoolman(int(s_id), uid)
    db.session.add(SpoolmanSyncLog(rfid_uid=uid, spoolman_id=int(s_id), success=success, message=msg))
    db.session.commit()
    color = "#35AB57" if success else "#E72A2E"
    return f"<div class='p-3 border rounded text-sm mt-3' style='border-color:{color}; color:{color}; bg-color:{color}20;'>{msg}</div>"

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)