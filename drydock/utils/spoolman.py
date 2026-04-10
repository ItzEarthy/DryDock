from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime

from ..models import AppSettings
from .database import SERVICE_STATUS_TTL_SECONDS, _SERVICE_STATUS_CACHE, get_or_create


# Caches for external Spoolman network requests
_SPOOLMAN_DATA_CACHE = {
    "spools": {"at": None, "data": []},
    "filaments": {"at": None, "data": []},
}


def _spoolman_request(path, method="GET", payload=None, timeout=3.0, base_url=None):
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

    try:
        if not req.full_url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid URL scheme: {req.full_url}")

        with urllib.request.urlopen(req, timeout=timeout) as response:  # nosec B310
            body = response.read().decode("utf-8").strip()
            if not body:
                return {}
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"raw": body}
    except urllib.error.HTTPError as he:
        try:
            err_body = he.read().decode("utf-8").strip()
        except Exception:
            err_body = None
        msg = f"HTTP Error {he.code}: {he.reason}"
        if err_body:
            msg = f"{msg} - {err_body}"
        raise Exception(msg)
    except urllib.error.URLError as ue:
        raise Exception(str(ue))


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
        _spoolman_request("/api/v1/info", method="GET", timeout=3.0, base_url=url)
        result = (True, "Connected")
    except Exception as exc:
        # Surface the exception message to make troubleshooting easier in UI and logs
        msg = str(exc) or "Unreachable"
        result = (False, msg)

    cache["at"] = now
    cache["key"] = key
    cache["value"] = result
    return result


def fetch_active_spools(limit=25):
    cache = _SPOOLMAN_DATA_CACHE["spools"]
    now = datetime.utcnow()

    if cache["at"] and (now - cache["at"]).total_seconds() < 15:
        return cache["data"][:limit]

    endpoints = [f"/api/v1/spool?limit={limit}", f"/api/v1/spool"]
    for endpoint in endpoints:
        try:
            payload = _spoolman_request(endpoint)
            spools = _normalize_collection(payload)
            if spools:
                cache["at"] = now
                cache["data"] = spools
                return spools[:limit]
        except Exception:
            continue
    return []


def fetch_filament_options(limit=150):
    cache = _SPOOLMAN_DATA_CACHE["filaments"]
    now = datetime.utcnow()

    if cache["at"] and (now - cache["at"]).total_seconds() < 15:
        return cache["data"][:limit]

    endpoints = [f"/api/v1/filament?limit={limit}", "/api/v1/filament"]
    for endpoint in endpoints:
        try:
            payload = _spoolman_request(endpoint)
            filaments = _normalize_collection(payload)
            if filaments:
                cache["at"] = now
                cache["data"] = filaments
                return filaments[:limit]
        except Exception:
            continue
    return []
