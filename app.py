"""DryDock entrypoint.

This file is intentionally kept small.
All application code lives in the `drydock/` package (app factory, models,
blueprints, utils, and scheduled tasks).
"""

from __future__ import annotations

import os

from drydock import create_app
from drydock.tasks import start_scheduler

app = create_app()


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() in ("true", "1", "t")

    # Mirror the original behavior: only start the scheduler in the reloader's
    # "main" process.
    if not debug_mode or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_scheduler(app)

    host_ip = "0.0.0.0"  # nosec B104
    app.run(host=host_ip, port=5000, debug=debug_mode)
