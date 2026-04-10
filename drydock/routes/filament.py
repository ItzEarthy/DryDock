from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean

from flask import Blueprint, render_template, request, session

from ..models import AppSettings, CalibrationSettings, SensorLog, SpoolmanSyncLog
from ..utils.database import get_or_create
from ..utils.logging import format_uptime, APP_START_TIME, log_event
from ..utils.scale import _to_float, _to_int, calculate_weight_grams, compute_weight_stability
from ..utils.spoolman import _spoolman_request, check_spoolman, fetch_active_spools, fetch_filament_options
from .auth import login_required

from .dashboard import build_context


filament_bp = Blueprint("filament", __name__, url_prefix="/filaments")


@filament_bp.route("/")
def index():
    return render_template("filament_management.html", **build_context(include_spools=True))


@filament_bp.route("/partials/<section>")
def render_partial(section):
    allowed = {"spool_list", "filament_options"}
    if section not in allowed:
        return "Not found", 404
    include_spools = section == "spool_list"
    include_filaments = section == "filament_options"
    ctx = build_context(include_spools=include_spools)
    if include_filaments:
        ctx["filament_options"] = fetch_filament_options()
    return render_template(f"partials/{section}.html", **ctx)


@filament_bp.post("/spoolman/sync")
def spoolman_sync():
    spoolman_id = (request.form.get("spoolman_id") or "").strip()
    rfid_uid = (request.form.get("rfid_uid") or "").strip()
    weight = _to_float(request.form.get("weight"))
    empty_weight = _to_float(request.form.get("empty_weight"))

    if not spoolman_id.isdigit():
        return "<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>Invalid spool ID. Please select a spool.</div>", 200
    if not rfid_uid:
        return "<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>RFID UID is missing. Please scan a tag first.</div>", 200
    if weight is None:
        weight = 0.0
    if empty_weight is None:
        empty_weight = 0.0

    remaining = max(0.0, weight - empty_weight)
    import json
    payload = {"id": int(spoolman_id), "remaining_weight": remaining, "extra": {"rfid_uid": json.dumps(rfid_uid)}}
    try:
        _spoolman_request(f"/api/v1/spool/{int(spoolman_id)}", method="PATCH", payload=payload)
        from ..extensions import db

        db.session.add(
            SpoolmanSyncLog(
                rfid_uid=rfid_uid,
                spoolman_id=int(spoolman_id),
                success=True,
                message=f"Synced with remaining weight {remaining}",
            )
        )
        db.session.commit()
        log_event("INFO", "spool_sync", spoolman_id=spoolman_id, rfid_uid=rfid_uid, weight=remaining)
        return f"<div class='font-bold text-[#35AB57] text-center p-2 border border-[#35AB57] rounded'>Saved!</div>"
    except Exception as exc:
        try:
            from ..extensions import db
            db.session.add(
                SpoolmanSyncLog(
                    rfid_uid=rfid_uid,
                    spoolman_id=int(spoolman_id),
                    success=False,
                    message=str(exc),
                )
            )
            db.session.commit()
        except:
            pass
        log_event("ERROR", "spool_sync_failed", spoolman_id=spoolman_id, rfid_uid=rfid_uid, error=str(exc))
        
        # Simplify error string for the user
        err_msg = str(exc)
        if "400" in err_msg or "Bad Request" in err_msg:
             err_msg = "Invalid input or Spoolman rejected request."
        elif "WinError 10061" in err_msg:
             err_msg = "Could not connect to Spoolman."
             
        return f"<div class='font-bold text-[#E72A2E] text-center p-2 border border-[#E72A2E] rounded'>Failed: {err_msg}</div>", 200


@filament_bp.post("/spoolman/action")
def spoolman_action():
    action = (request.form.get("action") or "").strip().lower()
    spool_id = _to_int(request.form.get("spool_id"))
    if spool_id is None:
        return "<div class='text-[#E72A2E] text-sm p-3 border border-[#E72A2E] rounded'>Spool ID missing.</div>", 200

    try:
        if action == "reweigh":
            weight = _to_float(request.form.get("weight"))
            empty_weight = _to_float(request.form.get("empty_weight"))
            if weight is None:
                current = build_context(include_spools=False)
                weight = current["stability"]["stable_weight"] or current["weight_grams"] or 0.0
            if empty_weight is None:
                empty_weight = 0.0
            remaining_weight = max(0.0, weight - empty_weight)
            payload = {"id": spool_id, "remaining_weight": remaining_weight}
            _spoolman_request(f"/api/v1/spool/{spool_id}", method="PATCH", payload=payload)
            message = f"Spool {spool_id} re-weighed to {round(remaining_weight, 1)}g (Measured: {round(weight, 1)}g)"
        elif action == "mark_used":
            payload = {"id": spool_id, "remaining_weight": 0}
            _spoolman_request(f"/api/v1/spool/{spool_id}", method="PATCH", payload=payload)
            message = f"Spool {spool_id} marked used"
        elif action == "archive":
            payload = {"id": spool_id, "archived": True}
            _spoolman_request(f"/api/v1/spool/{spool_id}", method="PATCH", payload=payload)
            message = f"Spool {spool_id} archived"
        elif action == "unlink":
            import json
            # Set to empty JSON string to effectively clear the RFID without breaking the schema
            payload = {"id": spool_id, "extra": {"rfid_uid": json.dumps("")}}
            _spoolman_request(f"/api/v1/spool/{spool_id}", method="PATCH", payload=payload)
            message = f"RFID unlinked from Spool {spool_id}"
        elif action == "remove":
            _spoolman_request(f"/api/v1/spool/{spool_id}", method="DELETE")
            message = f"Spool {spool_id} removed"
        else:
            return "<div class='text-[#E72A2E] text-sm p-3 border border-[#E72A2E] rounded'>Unknown action.</div>", 200

        log_event("INFO", "spoolman_action", action=action, spool_id=spool_id)
        return render_template(
            "partials/spool_list.html",
            action_message=message,
            **build_context(include_spools=True),
        )
    except Exception as exc:
        return render_template(
            "partials/spool_list.html",
            action_message=f"Action failed: {exc}",
            action_error=True,
            **build_context(include_spools=True),
        )


@filament_bp.post("/spoolman/add_filament")
def spoolman_add_filament():
    filament_id = _to_int(request.form.get("filament_id"))
    rfid_uid = (request.form.get("rfid_uid") or "").strip()
    remaining_weight = _to_float(request.form.get("remaining_weight"))

    if filament_id is None or not rfid_uid:
        return "<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>Filament selection and RFID UID are required.</div>", 200
    if remaining_weight is None:
        remaining_weight = 0.0

    import json
    payload = {
        "filament_id": filament_id,
        "remaining_weight": remaining_weight,
        "extra": {"rfid_uid": json.dumps(rfid_uid)},
    }

    try:
        _spoolman_request("/api/v1/spool", method="POST", payload=payload)
        log_event(
            "INFO",
            "spool_added",
            filament_id=filament_id,
            rfid_uid=rfid_uid,
            remaining_weight=remaining_weight,
        )
        return "<div class='p-3 border border-[#35AB57] text-[#35AB57] rounded text-sm'>New filament spool created and linked to RFID.</div>"
    except Exception as exc:
        return f"<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>Failed to create spool: {exc}</div>", 200


@filament_bp.get("/wizard/modal")
def wizard_modal():
    return render_template("partials/filament_wizard.html", **build_context(include_spools=True))


@filament_bp.route("/wizard/step/<step_name>", methods=["GET", "POST"])
def wizard_step(step_name):
    context = build_context(include_spools=True)

    selected_spool_id = None
    latest_uid = (context.get("latest_uid") or "").strip()
    if latest_uid:
        for spool in context.get("spoolman_spools", []):
            spool_extra = spool.get("extra") if isinstance(spool, dict) else getattr(spool, "extra", None)
            spool_rfid = None
            if isinstance(spool_extra, dict):
                spool_rfid = (spool_extra.get("rfid_uid") or spool_extra.get("rfid") or "").strip()
            if not spool_rfid:
                spool_rfid = (
                    (spool.get("rfid_uid") if isinstance(spool, dict) else getattr(spool, "rfid_uid", None))
                    or ""
                )
                spool_rfid = spool_rfid.strip() if spool_rfid else ""
            if spool_rfid and spool_rfid == latest_uid:
                spool_id_val = (
                    (spool.get("id") if isinstance(spool, dict) else getattr(spool, "id", None))
                    or (spool.get("spool_id") if isinstance(spool, dict) else getattr(spool, "spool_id", None))
                )
                try:
                    selected_spool_id = str(int(spool_id_val))
                except Exception:
                    selected_spool_id = str(spool_id_val)
                break
    context["selected_spool_id"] = selected_spool_id

    if step_name == "clear_scan":
        if request.method == "POST":
            from .dashboard import _perform_software_tare

            success, message = _perform_software_tare()
            context["wizard_message"] = message
            context["wizard_error"] = not success
            if not success:
                return render_template("partials/wizard_clear_scan.html", **context), 200
            return render_template("partials/wizard_add_spool.html", **context)
        return render_template("partials/wizard_clear_scan.html", **context)

    if step_name == "add_spool":
        return render_template("partials/wizard_add_spool.html", **context)

    if step_name in {"harden", "harden_status", "confirm"}:
        sw = request.args.get("selected_weight")
        if sw:
            try:
                context["selected_weight"] = float(sw)
            except Exception:
                context["selected_weight"] = context["stability"]["stable_weight"] or context["weight_grams"] or 0
        else:
            context["selected_weight"] = context["stability"]["stable_weight"] or context["weight_grams"] or 0
        return render_template(f"partials/wizard_{step_name}.html", **context)

    return "Unknown wizard step", 404


@filament_bp.post("/wizard/step/accept")
def wizard_accept():
    spool_id = _to_int(request.form.get("spoolman_id"))
    rfid_uid = (request.form.get("rfid_uid") or "").strip()
    weight = _to_float(request.form.get("weight"))
    if spool_id is None:
        return "<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>Spool ID is required.</div>", 200
    if not rfid_uid:
        return "<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>RFID UID is missing.</div>", 200
    if weight is None:
        weight = 0.0

    empty_weight_val = 0.0
    try:
        spool_data = _spoolman_request(f"/api/v1/spool/{int(spool_id)}")
        empty_weight_val = spool_data.get("spool_weight")
        if empty_weight_val is None:
            filament = spool_data.get("filament", {})
            empty_weight_val = getattr(filament, "get", lambda k,d: d)("spool_weight", 0)
        empty_weight_val = empty_weight_val or 0.0
    except Exception:
        empty_weight_val = 0.0

    remaining = max(0.0, weight - empty_weight_val)

    import json
    payload = {"id": int(spool_id), "remaining_weight": remaining, "extra": {"rfid_uid": json.dumps(rfid_uid)}}
    try:
        log_event(
            "DEBUG",
            "spool_sync_attempt",
            payload=payload,
            endpoint=f"/api/v1/spool/{int(spool_id)}",
        )
        result = _spoolman_request(f"/api/v1/spool/{int(spool_id)}", method="PATCH", payload=payload)
        log_event("DEBUG", "spool_sync_response", response=result)
        from ..extensions import db

        db.session.add(
            SpoolmanSyncLog(
                rfid_uid=rfid_uid,
                spoolman_id=int(spool_id),
                success=True,
                message=f"Wizard synced with remaining weight {remaining}",
            )
        )
        db.session.commit()
        log_event("INFO", "spool_sync", spoolman_id=spool_id, rfid_uid=rfid_uid, weight=remaining)
        return f"<div class='p-3 border border-[#35AB57] text-[#35AB57] rounded text-sm'>Wizard complete: spool updated. Measured: {weight}g (Net: {remaining}g)</div>"
    except Exception as exc:
        try:
            from ..extensions import db

            db.session.add(
                SpoolmanSyncLog(
                    rfid_uid=rfid_uid,
                    spoolman_id=int(spool_id) if spool_id is not None else None,
                    success=False,
                    message=str(exc),
                )
            )
            db.session.commit()
        except Exception:
            pass
        log_event(
            "ERROR",
            "spool_sync_failed",
            spoolman_id=spool_id,
            rfid_uid=rfid_uid,
            error=str(exc),
        )
        return f"<div class='p-3 border border-[#E72A2E] text-[#E72A2E] rounded text-sm'>Wizard sync failed: {exc}</div>", 200


__all__ = ["filament_bp"]
