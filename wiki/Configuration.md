# Configuration

This page covers all configuration options available in DryDock, including the `.env` file written by the installer and every setting available in the web-based Settings page.

## The .env File

The installer creates a `.env` file in the project root directory. This file stores environment-level configuration that is needed before the application starts. You can view or edit it directly:

```bash
nano ~/DryDock/.env
```

### .env Keys

| Key | Description | Example |
|---|---|---|
| `WIFI_SSID` | The Wi-Fi network name that will be injected into the ESP32 firmware. | `MyHomeWifi` |
| `WIFI_PASS` | The Wi-Fi password injected into the firmware. | `mysecretpassword` |
| `BOARD_ID` | The PlatformIO board identifier for your ESP32 variant. | `esp32-s3-devkitc-1` |
| `PI_IP` | The local IP address of the host running DryDock. Auto-detected by the installer. | `192.168.1.50` |

**Note:** The `PI_IP` value is refreshed every time you run `install.sh`. If your Pi's IP address changes, re-run the installer with the `-f` flag to update it:

```bash
bash install.sh -f
```

## Application Settings (Web Interface)

All application settings are managed through the dashboard and stored in the SQLite database. No manual file editing is required. To access the settings, open the dashboard, log in, and navigate to the **Settings** page.

### Spoolman URL

The full base URL of your Spoolman instance. DryDock uses this address to fetch spool data and to PATCH remaining weight values after each scan and weigh cycle.

**Default:** `http://localhost:8000`

**Example:** `http://192.168.1.55:7912`

After changing this value, click **Test Connection** to verify that DryDock can reach Spoolman before saving.

### Humidity Threshold

The minimum acceptable humidity delta (in percent) between the inside and outside readings. If the measured delta (inside minus ambient) falls below this value, the dashboard flags the desiccant as saturated and you should replace or regenerate the silica gel.

**Default:** `10.0` (10%)

A higher value means you will be alerted sooner when the desiccant begins to saturate. A lower value gives more tolerance before an alert is triggered.

### Log Retention Days

How many days of sensor logs to keep in the database. A background job runs every 24 hours and deletes records older than this threshold. Keeping logs for a shorter period reduces database size on systems with limited storage.

**Default:** `7` days

### Calibration Reminder Days

After this many days have passed since the last scale calibration, the dashboard will display a reminder banner. This is purely a reminder - calibration is not forced.

**Default:** `30` days

### Backup Interval Hours

How often (in hours) the system should automatically create a backup of the SQLite database. Backups are stored in the `instance/backups/` directory.

**Default:** `24` hours

### Backup Retention Count

The maximum number of automatic backup files to keep. When a new backup is created and the count exceeds this number, the oldest backup file is deleted.

**Default:** `10`

### Theme

The visual theme of the dashboard.

| Option | Description |
|---|---|
| `dark` | Dark background with light text (default) |
| `light` | Light background with dark text |

### Log Level

Controls the verbosity of the structured event log written to `instance/logs/drydock.jsonl`.

| Option | Description |
|---|---|
| `INFO` | Logs significant events only (spool syncs, calibration, settings changes) |
| `DEBUG` | Logs all events including every incoming telemetry update from the ESP32 |

**Default:** `INFO`

Set to `DEBUG` temporarily if you need to diagnose a communication issue. Switch back to `INFO` for normal operation, as DEBUG mode generates a large amount of log data.

## Spoolman Integration

DryDock is designed to work alongside [Spoolman](https://github.com/Donkie/Spoolman), a self-hosted filament spool tracking service.

### How the Integration Works

1. Each filament spool in Spoolman has a numeric ID.
2. DryDock stores a mapping between a spool's Spoolman ID and the RFID tag UID attached to the physical spool. This mapping is stored in the `extra.rfid_uid` field of the Spoolman spool record.
3. When you scan a spool, DryDock reads the RFID UID and looks for a matching spool in Spoolman.
4. After weighing, DryDock sends an HTTP PATCH request to Spoolman to update the `remaining_weight` field of that spool.

### Configuring Spoolman

1. Install and start Spoolman. The default Spoolman port is `7912` if running via Docker, or `8000` if running from source.
2. In the DryDock Settings page, set the **Spoolman URL** to the full base URL of your Spoolman instance.
3. Click **Test Connection** to confirm DryDock can reach it.

### Creating Filament Records in Spoolman

Spoolman requires a **Filament** record to exist before you can create a **Spool** record. Create your filament types (brand, material, color, weight) in the Spoolman interface first, then use DryDock's **Add New Spool** wizard to create spool records and link them to RFID tags.

### RFID Linking

The link between a physical spool and a Spoolman record is created during the spool wizard flow in DryDock. Once a spool is linked, Spoolman stores the RFID UID in the spool's `extra` metadata field. You can unlink an RFID tag from a spool using the **Unlink** action in the Filament Management page.

## Exporting and Importing Settings

DryDock allows you to export the current application settings and calibration data to a JSON file for backup or migration purposes.

**To export:** On the Settings page, click **Export Config**. The browser will download a file named `drydock_config.json`.

A typical export file looks like this:

```json
{
  "exported_at": "2024-01-15T10:30:00Z",
  "app_settings": {
    "spoolman_url": "http://192.168.1.55:7912",
    "humidity_threshold": 10.0,
    "log_retention_days": 7,
    "theme": "dark",
    "log_level": "INFO",
    "calibration_reminder_days": 30,
    "backup_interval_hours": 24,
    "backup_retention_count": 10,
    "last_calibration_at": "2024-01-10T09:00:00"
  },
  "calibration": {
    "tare_offset": 12345.67,
    "calibration_multiplier": 0.002341
  }
}
```

**To import:** On the Settings page, use the **Import Config** file picker to upload a previously exported JSON file. All recognized fields are applied immediately.

## Database Backups

The SQLite database (stored at `instance/drydock.db`) is automatically backed up on the schedule you configure. Backup files are stored in `instance/backups/` and are named with a timestamp for easy identification.

You can also create a manual backup at any time from the Settings page by clicking **Create Backup Now**.

If you need to restore from a backup, stop the DryDock service, replace `instance/drydock.db` with your chosen backup file, and restart the service:

```bash
sudo systemctl stop drydock
cp ~/DryDock/instance/backups/drydock_<timestamp>.db ~/DryDock/instance/drydock.db
sudo systemctl start drydock
```

## Moonraker Update Manager (Optional)

If you use Klipper with Moonraker, the installer can add DryDock to Moonraker's update manager. This adds a DryDock card to the Mainsail or Fluidd update interface. The entry added to `moonraker.conf` looks like this:

```ini
[update_manager drydock]
type: git_repo
path: /home/pi/DryDock
origin: https://github.com/ItzEarthy/DryDock.git
primary_branch: main
is_system_service: False
```

You can add this manually to your `moonraker.conf` if you skipped this step during installation.
