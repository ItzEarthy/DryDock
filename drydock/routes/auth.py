from __future__ import annotations

import time
from datetime import datetime
from functools import wraps

from flask import Blueprint, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import User


auth_bp = Blueprint("auth", __name__)

_HAS_USER_CACHE = {"at": None, "value": None}


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return redirect(url_for("auth.login"))
        return fn(*args, **kwargs)

    return wrapper


# Backwards-compatible name: older code used admin_required.
admin_required = login_required


@auth_bp.app_context_processor
def inject_user():
    user = get_current_user()
    return {"current_user": user}


@auth_bp.before_app_request
def check_setup():
    # Start request timer early (this runs before auth redirects).
    try:
        request._start_time = time.perf_counter()
    except Exception:
        request._start_time = None

    path = request.path or "/"
    if path.startswith("/static") or path.startswith("/api/update"):
        return

    public_paths = {"/login", "/setup", "/favicon.ico"}

    # Avoid querying User table on every request.
    now = datetime.utcnow()
    if _HAS_USER_CACHE["at"] and (now - _HAS_USER_CACHE["at"]).total_seconds() < 10:
        has_user = bool(_HAS_USER_CACHE["value"])
    else:
        has_user = User.query.first() is not None
        _HAS_USER_CACHE["at"] = now
        _HAS_USER_CACHE["value"] = has_user

    if not has_user and path != "/setup":
        return redirect(url_for("auth.setup"))

    if has_user and "user_id" not in session and path not in public_paths:
        return redirect(url_for("auth.login"))


@auth_bp.after_app_request
def _log_request_timing(response):
    start = getattr(request, "_start_time", None)
    if start:
        duration_ms = (time.perf_counter() - start) * 1000.0
        try:
            response.headers["X-Process-Time-ms"] = f"{duration_ms:.2f}"
        except Exception:
            pass
    return response


@auth_bp.route("/setup", methods=["GET", "POST"])
def setup():
    if User.query.first():
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password")
        if username and password:
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
            )
            db.session.add(user)
            db.session.commit()
            # Update the in-memory cache so subsequent requests in this
            # redirect chain see that a user now exists and avoid a loop.
            _HAS_USER_CACHE["at"] = datetime.utcnow()
            _HAS_USER_CACHE["value"] = True
            session["user_id"] = user.id
            return redirect(url_for("dashboard.index"))

    return render_template("setup.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Basic anti-bruteforce delay
        time.sleep(1.0)
        
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            return redirect(url_for("dashboard.index"))
        return render_template("login.html", login_error="Invalid credentials", username=username), 401
    return render_template("login.html", username="")


@auth_bp.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("auth.login"))


__all__ = ["auth_bp", "login_required", "admin_required", "get_current_user"]
