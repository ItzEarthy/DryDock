# API Reference

This page documents all HTTP endpoints exposed by the DryDock Flask backend. The API is used primarily by the ESP32 firmware to post telemetry and by the frontend dashboard, but you can call any endpoint directly using tools such as `curl` or any HTTP client.

All endpoints are relative to the base URL of your DryDock instance (for example, `http://192.168.1.50:5000`).

---

## Telemetry Endpoint

### POST /api/update

The primary data ingestion endpoint. The ESP32 calls this endpoint on its heartbeat interval (every 5 seconds by default) and whenever a significant event occurs (RFID scan, large weight change).

**Authentication:** None. This endpoint is intentionally public so the ESP32 does not need credentials.

**Request Body (JSON):**

```json
{
  "temp_1": 22.5,
  "hum_1": 35.2,
  "temp_2": 24.1,
  "hum_2": 58.7,
  "raw_adc": 1234567,
  "weight": 312.45,
  "hardening_progress": 100,
  "rfid_uid": "A1B2C3D4"
}
```

| Field | Type | Description |
|---|---|---|
| `temp_1` | float | Temperature in Celsius from AM2320 #1 (inside dry box). |
| `hum_1` | float | Relative humidity in percent from AM2320 #1 (inside dry box). |
| `temp_2` | float | Temperature in Celsius from AM2320 #2 (ambient). |
| `hum_2` | float | Relative humidity in percent from AM2320 #2 (ambient). |
| `raw_adc` | integer | Raw 24-bit ADC reading from the NAU7802. Preferred over `weight`. |
| `weight` | float | Pre-computed weight in grams. Used only if `raw_adc` is not provided. |
| `hardening_progress` | integer | Weight stability progress (0-100). Informational. |
| `rfid_uid` | string | Uppercase hexadecimal UID of the most recently scanned RFID tag. |

All fields are optional. Missing or `null` fields are stored as `null` in the database. At minimum, at least one of `raw_adc` or `weight` should be present for weight tracking to function.

**Response (201 Created):**

```json
{"status": "success"}
```

**Response (400 Bad Request):**

```json
{"error": "No data"}
```

---

## Live Data Endpoints

### GET /api/live_snapshot

Returns the most recent sensor reading and the latest known RFID UID. Used by the dashboard to update the live display.

**Authentication:** None.

**Response (200 OK):**

```json
{
  "ok": true,
  "weight_grams": 312.45,
  "raw_adc": 1234567,
  "tare_offset": 12300.5,
  "rfid_uid": "A1B2C3D4",
  "timestamp": "2024-01-15T10:30:00"
}
```

| Field | Type | Description |
|---|---|---|
| `ok` | boolean | `true` if telemetry has been received within the last 3 minutes. |
| `weight_grams` | float or null | Current calibrated weight in grams. `null` if ESP32 is offline. |
| `raw_adc` | integer or null | Latest raw ADC value. `null` if ESP32 is offline. |
| `tare_offset` | float | Current tare offset stored in the database. |
| `rfid_uid` | string | UID of the most recently scanned RFID tag. Empty string if none. |
| `timestamp` | string | ISO 8601 timestamp of the most recent telemetry record. |

---

### GET /api/weight/stability

Returns the current weight stability status, computed from the last 8 telemetry records.

**Authentication:** None.

**Response (200 OK):**

```json
{
  "progress": 100,
  "stable": true,
  "stable_weight": 312.45,
  "ema_weight": 312.45,
  "samples": 8
}
```

| Field | Type | Description |
|---|---|---|
| `progress` | integer | Stability progress from 0 to 100. 100 means the reading is settled. |
| `stable` | boolean | `true` when the weight reading is considered stable. |
| `stable_weight` | float or null | The current stable weight in grams. `null` if no data available. |
| `ema_weight` | float or null | The current EMA-smoothed weight value. |
| `samples` | integer | Number of recent samples used to compute stability. |

---

## Historical Data

### GET /api/history

Returns time-series sensor data for display in the dashboard charts.

**Authentication:** None.

**Query Parameters:**

| Parameter | Default | Options | Description |
|---|---|---|---|
| `range` | `24h` | `1h`, `24h`, `7d` | Time range to fetch. |
| `aggregation` | `avg` | `avg`, `min`, `max`, `raw` | How to aggregate data within each time bucket. |

**Response (200 OK):**

```json
{
  "labels": ["2024-01-15T09:00:00", "2024-01-15T09:05:00"],
  "hum_1": [35.2, 36.0],
  "hum_2": [58.7, 59.1],
  "temp_1": [22.5, 22.6],
  "temp_2": [24.1, 24.3],
  "weight": [312.45, null],
  "anomalies": [],
  "threshold": 10.0,
  "range": "24h",
  "aggregation": "avg"
}
```

The `anomalies` array contains `{x, y}` objects for each time point where the humidity delta (`hum_2 - hum_1`) fell below the configured threshold.

---

## System Health

### GET /api/system/health

Returns a summary of the DryDock system health.

**Authentication:** None.

**Response (200 OK):**

```json
{
  "uptime": "2 days, 4 hours, 17 minutes",
  "esp32": {
    "ok": true,
    "msg": "Online"
  },
  "spoolman": {
    "ok": true,
    "msg": "Connected"
  },
  "database": {
    "ok": true,
    "msg": "Healthy"
  }
}
```

---

## Scale Control

### POST /api/scale/remote_tare

Performs a software tare using the latest available raw ADC reading from the database. This is equivalent to clicking the Tare button in the calibration panel. Can be called by external automation.

**Authentication:** None (designed for ESP32 or automation use).

**Response (200 OK):**

```json
{"ok": true, "message": "Scale tared using latest telemetry sample."}
```

**Response (400 Bad Request):**

```json
{"ok": false, "message": "No sensor data available to tare."}
```

---

## Log Downloads

### GET /api/logs/download

Downloads sensor logs as a file attachment. Returns logs for the specified time window.

**Authentication:** None.

**Query Parameters:**

| Parameter | Default | Description |
|---|---|---|
| `format` | `csv` | Output format. Use `csv` or `json`. |
| `hours` | `168` (7 days) | Number of hours of history to include. |

**Example requests:**

```bash
# Download as CSV (last 7 days)
curl http://192.168.1.50:5000/api/logs/download -o logs.csv

# Download as JSON (last 24 hours)
curl "http://192.168.1.50:5000/api/logs/download?format=json&hours=24" -o logs.json
```

**CSV columns:**

```
Timestamp, Temp_1, Hum_1, Temp_2, Hum_2, Raw_ADC, RFID_UID, Weight_grams
```

---

### GET /api/logs/structured/download

Downloads the structured application event log (`drydock.jsonl`). This log contains all application events such as spool syncs, calibrations, settings changes, and errors in newline-delimited JSON format.

**Authentication:** None.

**Response:** A file download (`drydock_events.jsonl`). Returns `404` if no log file exists yet.

**Example:**

```bash
curl http://192.168.1.50:5000/api/logs/structured/download -o events.jsonl
```

---

## Notes on Authentication

Most read-only and ESP32-facing endpoints require no authentication. The following routes do require a login session:

- `POST /settings` (save settings)
- `GET /settings/export` (export configuration)
- `POST /settings/import` (import configuration)
- `POST /settings/backup` (create manual backup)
- `POST /calibration/tare` (tare the scale)
- `POST /calibration/multiplier` (set calibration multiplier)
- `POST /calibration/samples/*` (guided calibration steps)
- `POST /build_firmware` (generate firmware file)

If you call these endpoints without a valid session cookie, you will be redirected to the login page (HTTP 302).
