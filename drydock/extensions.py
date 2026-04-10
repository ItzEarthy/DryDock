from __future__ import annotations

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

# Shared Flask extensions live here to prevent circular imports.
db = SQLAlchemy()
migrate = Migrate()
