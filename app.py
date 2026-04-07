import json, os, urllib.request, urllib.error, csv, requests
from datetime import datetime, timedelta
from io import BytesIO, StringIO

from flask import Flask, jsonify, render_template, request, redirect, url_for, session, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from flask_migrate import Migrate

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

class SpoolmanSyncLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    rfid_uid = db.Column(db.String(64), nullable=False)
    spoolman_id = db.Column(db.Integer, nullable=False)
    success = db.Column(db.Boolean, nullable=False)
    message = db.Column(db.String(500), nullable=True)

# --- AUTH ---
@app.before_request
def check_setup():
    if request.path.startswith('/api/update') or request.path.startswith('/static'): return
    if not User.query.first():
        if request.path != '/setup': return redirect(url_for('setup'))
    if User.query.first() and 'user_id' not in session and request.path not in ['/login', '/setup']:
        return redirect(url_for('login'))

@app.route("/setup", methods=["GET", "POST"])
def setup():
    if User.query.first(): return redirect(url_for('index'))
    if request.method == "POST":
        u, p = request.form.get("username"), request.form.get("password")
        if u and p:
            db.session.add(User(username=u, password_hash=generate_password_hash(p)))
            db.session.commit()
            session['user_id'] = User.query.first().id
            return redirect(url_for('index'))
    return render_template("setup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form.get("username")).first()
        if user and check_password_hash(user.password_hash, request.form.get("password")):
            session['user_id'] = user.id
            return redirect(url_for('index'))
        return "Invalid credentials", 401
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# --- TASKS ---
def prune_old_logs():
    with app.app_context():
        s = AppSettings.query.first()
        if s and s.log_retention_days > 0:
            SensorLog.query.filter(SensorLog.timestamp < datetime.utcnow() - timedelta(days=s.log_retention_days)).delete()
            db.session.commit()

scheduler = BackgroundScheduler()
scheduler.add_job(func=prune_old_logs, trigger="interval", hours=24)
scheduler.start()

# --- HELPERS ---
def _to_float(v):
    try: return float(v)
    except: return None

def get_or_create(model):
    obj = model.query.first()
    if not obj:
        obj = model()
        db.session.add(obj)
        db.session.commit()
    return obj

def trigger_webhook(message):
    s = get_or_create(AppSettings)
    if s.webhook_url:
        try: requests.post(s.webhook_url, json={"content": message}, timeout=2)
        except: pass

def check_spoolman(url):
    if not url: return False, "Not Configured"
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/api/v1/info", method="GET")
        with urllib.request.urlopen(req, timeout=2) as r:
            if r.getcode() == 200: return True, "Connected"
    except: pass
    return False, "Unreachable"

def build_context():
    log = SensorLog.query.order_by(SensorLog.timestamp.desc()).first()
    cal = get_or_create(CalibrationSettings)
    sett = get_or_create(AppSettings)
    
    uid_log = SensorLog.query.filter(SensorLog.rfid_uid.isnot(None), SensorLog.rfid_uid != "").order_by(SensorLog.timestamp.desc()).first()
    
    ctx = {
        "log": log, "cal_settings": cal, "app_settings": sett,
        "latest_uid": uid_log.rfid_uid if uid_log else "",
        "hum_delta": None, "weight_grams": None, "desiccant_healthy": None,
        "sensor_status": {"ok": False, "msg": "No Data"},
        "spoolman_status": {"ok": False, "msg": "Unreachable"}
    }

    if log:
        ctx["sensor_status"] = {"ok": True, "msg": "Online"} if (datetime.utcnow() - log.timestamp).total_seconds() < 300 else {"ok": False, "msg": "Offline"}
        if log.hum_1 and log.hum_2:
            ctx["hum_delta"] = log.hum_2 - log.hum_1
            ctx["desiccant_healthy"] = ctx["hum_delta"] >= sett.humidity_threshold
        if log.raw_adc:
            ctx["weight_grams"] = (log.raw_adc - cal.tare_offset) * cal.calibration_multiplier

    ctx["spoolman_status"]["ok"], ctx["spoolman_status"]["msg"] = check_spoolman(sett.spoolman_url)
    return ctx

# --- ROUTES ---
@app.route("/")
def index(): return render_template("index.html", **build_context())

@app.route("/settings_page")
def settings_page(): return render_template("settings.html", **build_context())

@app.route("/partials/<section>")
def render_partial(section): return render_template(f"partials/{section}.html", **build_context())

@app.route("/api/update", methods=["POST"])
def update_data():
    data = request.get_json(silent=True)
    if not data: return jsonify({"error": "No data"}), 400
    db.session.add(SensorLog(
        temp_1=_to_float(data.get("temp_1")), hum_1=_to_float(data.get("hum_1")),
        temp_2=_to_float(data.get("temp_2")), hum_2=_to_float(data.get("hum_2")),
        raw_adc=_to_float(data.get("raw_adc")), rfid_uid=str(data.get("rfid_uid")).strip() if data.get("rfid_uid") else None
    ))
    db.session.commit()
    return jsonify({"status": "success"}), 201

@app.post("/settings")
def save_settings():
    s = get_or_create(AppSettings)
    s.spoolman_url = request.form.get("spoolman_url", "")
    s.webhook_url = request.form.get("webhook_url", "")
    if _to_float(request.form.get("humidity_threshold")): s.humidity_threshold = _to_float(request.form.get("humidity_threshold"))
    if request.form.get("log_retention_days", "").isdigit(): s.log_retention_days = int(request.form.get("log_retention_days"))
    db.session.commit()
    return "<div class='p-3 bg-[#35AB57]/20 border border-[#35AB57] text-[#35AB57] rounded mt-4'>Settings Saved</div>"

@app.post("/calibration/tare")
def auto_tare():
    log = SensorLog.query.order_by(SensorLog.timestamp.desc()).first()
    if not log or log.raw_adc is None: return "<div class='text-[#E72A2E] text-sm mt-2'>No data</div>", 400
    c = get_or_create(CalibrationSettings)
    c.tare_offset = log.raw_adc
    db.session.commit()
    return render_template("partials/calibration.html", **build_context())

@app.post("/calibration/multiplier")
def auto_calibrate():
    known, log = _to_float(request.form.get("known_weight")), SensorLog.query.order_by(SensorLog.timestamp.desc()).first()
    if not known or not log or log.raw_adc is None: return "<div class='text-[#E72A2E] text-sm mt-2'>Invalid</div>", 400
    c = get_or_create(CalibrationSettings)
    diff = log.raw_adc - c.tare_offset
    if diff == 0: return "<div class='text-[#E72A2E] text-sm mt-2'>Scale unchanged</div>", 400
    c.calibration_multiplier = known / diff
    db.session.commit()
    return render_template("partials/calibration.html", **build_context())

@app.post("/spoolman/sync")
def spoolman_sync():
    s_id, uid = request.form.get("spoolman_id", "").strip(), request.form.get("rfid_uid", "").strip()
    if not s_id.isdigit() or not uid: return "<div class='text-[#E72A2E] text-sm'>Invalid Data.</div>", 400
    
    url = get_or_create(AppSettings).spoolman_url.rstrip("/")
    if not url: return "<div class='text-[#E72A2E] text-sm'>URL not configured.</div>", 400
    
    weight = request.form.get("weight", "0")
    payload = {"id": int(s_id), "remaining_weight": float(weight), "extra": {"rfid_uid": uid}}
    
    try:
        req = urllib.request.Request(f"{url}/api/v1/spool/{s_id}", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="PATCH")
        urllib.request.urlopen(req, timeout=5)
        return "<div class='p-3 border border-[#35AB57] text-[#35AB57] rounded text-sm'>Synced successfully!</div>"
    except Exception as e:
        return f"<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>Sync failed: {str(e)}</div>", 400

@app.route("/api/history")
def get_history():
    logs = SensorLog.query.filter(SensorLog.timestamp >= datetime.utcnow() - timedelta(hours=int(request.args.get("hours", 24)))).order_by(SensorLog.timestamp.asc()).all()
    return jsonify({
        "labels": [l.timestamp.strftime("%H:%M") for l in logs],
        "hum_1": [l.hum_1 for l in logs], "hum_2": [l.hum_2 for l in logs], "temp_1": [l.temp_1 for l in logs]
    })

@app.route("/api/logs/download")
def download_logs():
    logs = SensorLog.query.order_by(SensorLog.timestamp.desc()).limit(1000).all()
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Timestamp', 'Temp_1', 'Hum_1', 'Temp_2', 'Hum_2', 'Raw_ADC', 'RFID_UID'])
    for l in logs: cw.writerow([l.timestamp, l.temp_1, l.hum_1, l.temp_2, l.hum_2, l.raw_adc, l.rfid_uid])
    return Response(si.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=drydock_logs.csv"})

@app.route("/build_firmware", methods=["POST"])
def build_firmware():
    s, p, ip, pt = request.form.get("ssid",""), request.form.get("password",""), request.form.get("pi_ip",""), request.form.get("pi_port","")
    t = f'#include <WiFi.h>\n#include <HTTPClient.h>\nconst char* ssid="{s}";\nconst char* password="{p}";\nconst char* flask_server_url="http://{ip}:{pt}/api/update";\n// DryDock logic goes here.'
    b = BytesIO(); b.write(t.encode()); b.seek(0)
    return send_file(b, as_attachment=True, download_name="DryDock.ino", mimetype="text/plain")

if __name__ == "__main__": app.run(host="0.0.0.0", port=5000, debug=True)