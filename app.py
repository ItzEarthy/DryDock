import json
import os
import urllib.request
from datetime import datetime, timedelta
from io import BytesIO
from flask_migrate import Migrate

from flask import Flask, jsonify, render_template, request, redirect, url_for, session, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///drydock.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = "change_this_to_a_secure_random_string_in_production"
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

class AppSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    spoolman_url = db.Column(db.String(255), default="http://localhost:8000")
    humidity_threshold = db.Column(db.Float, default=10.0)
    log_retention_days = db.Column(db.Integer, default=7)

# --- AUTHENTICATION MIDDLEWARE ---
@app.before_request
def check_setup():
    # Allow setup route, static files, and the API endpoint to bypass auth
    if request.path.startswith('/api/update') or request.path.startswith('/static'):
        return
        
    if not User.query.first():
        if request.path != '/setup':
            return redirect(url_for('setup'))

@app.route("/setup", methods=["GET", "POST"])
def setup():
    if User.query.first():
        return redirect(url_for('index'))
        
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username and password:
            hashed = generate_password_hash(password)
            db.session.add(User(username=username, password_hash=hashed))
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

# --- BACKGROUND TASK (DATA PRUNING) ---
def prune_old_logs():
    with app.app_context():
        settings = AppSettings.query.first()
        if settings and settings.log_retention_days > 0:
            cutoff_date = datetime.utcnow() - timedelta(days=settings.log_retention_days)
            deleted = SensorLog.query.filter(SensorLog.timestamp < cutoff_date).delete()
            db.session.commit()
            print(f"Pruned {deleted} old sensor logs.")

scheduler = BackgroundScheduler()
scheduler.add_job(func=prune_old_logs, trigger="interval", hours=24)
scheduler.start()

# --- SCRIPT BUILDER ENDPOINT ---
@app.route("/build_firmware", methods=["POST"])
def build_firmware():
    if 'user_id' not in session: return "Unauthorized", 401
    
    ssid = request.form.get("ssid", "")
    wifi_pass = request.form.get("password", "")
    ip_addr = request.form.get("pi_ip", "192.168.1.100")
    port = request.form.get("pi_port", "5000")
    
    # Load your base C++ template (you can store this in a text file or as a string)
    template_str = """
#include <WiFi.h>
#include <HTTPClient.h>
// ... (rest of your includes) ...

const char* ssid = "{SSID}";
const char* password = "{PASS}";
const char* flask_server_url = "http://{IP}:{PORT}/api/update";

// ... (rest of your Arduino code) ...
"""
    
    custom_script = template_str.replace("{SSID}", ssid).replace("{PASS}", wifi_pass).replace("{IP}", ip_addr).replace("{PORT}", port)
    
    buffer = BytesIO()
    buffer.write(custom_script.encode('utf-8'))
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=True, download_name="DryDock_Node.ino", mimetype="text/plain")

# --- GRAPH DATA API ---
@app.route("/api/history")
def get_history():
    hours = int(request.args.get("hours", 24))
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    logs = SensorLog.query.filter(SensorLog.timestamp >= cutoff).order_by(SensorLog.timestamp.asc()).all()
    
    data = {
        "labels": [log.timestamp.strftime("%H:%M") for log in logs],
        "hum_1": [log.hum_1 for log in logs],
        "hum_2": [log.hum_2 for log in logs],
        "temp_1": [log.temp_1 for log in logs]
    }
    return jsonify(data)

# --- SPOOLMAN PROXY (For fetching Materials/Vendors) ---
@app.route("/api/spoolman/options")
def spoolman_options():
    settings = AppSettings.query.first()
    if not settings or not settings.spoolman_url:
        return jsonify({"error": "Spoolman URL not set"}), 400
        
    try:
        # Fetch vendors
        req_v = urllib.request.Request(f"{settings.spoolman_url.rstrip('/')}/api/v1/vendor", method="GET")
        with urllib.request.urlopen(req_v, timeout=2) as res:
            vendors = json.loads(res.read().decode('utf-8'))
            
        # Fetch filaments/materials
        req_f = urllib.request.Request(f"{settings.spoolman_url.rstrip('/')}/api/v1/filament", method="GET")
        with urllib.request.urlopen(req_f, timeout=2) as res:
            filaments = json.loads(res.read().decode('utf-8'))
            
        return jsonify({"vendors": vendors, "filaments": filaments})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)