from __future__ import annotations

from pathlib import Path

from flask import Flask

from .extensions import db, migrate
from datetime import datetime
from .utils.logging import set_app_start_time


def _bootstrap_app(app: Flask) -> None:
    # Keep the monolith's startup side effects, but run them when the app is created.
    from .models import AppSettings
    from .utils.database import ensure_first_admin, ensure_schema_extensions, get_or_create
    from .utils.logging import configure_structured_logging

    with app.app_context():
        ensure_schema_extensions()
        ensure_first_admin()
        configure_structured_logging(get_or_create(AppSettings).log_level)


def create_app(config_object: object | None = None) -> Flask:
    project_root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, root_path=str(project_root))

    # Record the application start time immediately after the Flask app is created
    set_app_start_time(datetime.utcnow())

    # Keep defaults identical to the monolith unless overridden.
    app.config.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///drydock.db")
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    # Flask sets SECRET_KEY=None by default, so setdefault() won't override it.
    # Mirror the monolith's always-present secret key unless explicitly set.
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = "drydock_secure_key_123"

    if config_object is not None:
        app.config.from_object(config_object)

    app.secret_key = app.config["SECRET_KEY"]

    db.init_app(app)
    migrate.init_app(app, db)

    # Import models so SQLAlchemy registers them.
    from . import models as _models  # noqa: F401

    from .routes.api import api_bp
    from .routes.auth import auth_bp
    from .routes.dashboard import dashboard_bp
    from .routes.filament import filament_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(filament_bp)

    _bootstrap_app(app)

    return app


__all__ = ["create_app", "db", "migrate"]
