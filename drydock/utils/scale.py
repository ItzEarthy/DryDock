from __future__ import annotations

import math

from statistics import mean

AUTO_ZERO_GRAMS = 8.0
AUTO_ZERO_ADJUST_ALPHA = 0.08


def _to_float(value):
    try:
        parsed = float(value)
        if math.isnan(parsed) or math.isinf(parsed):
            return None
        return parsed
    except (TypeError, ValueError):
        return None


def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def calculate_weight_grams(raw_adc, temp_1, calibration, settings):
    if raw_adc is None:
        return None

    multiplier = calibration.calibration_multiplier if calibration.calibration_multiplier else 1.0
    temp_factor = settings.temp_compensation_factor if settings.temp_compensation_factor is not None else 0.0
    ref_temp = settings.temp_reference_c if settings.temp_reference_c is not None else 25.0
    measured_temp = temp_1 if temp_1 is not None else ref_temp

    drift_adjustment = (measured_temp - ref_temp) * temp_factor
    compensated_raw = raw_adc - calibration.tare_offset - drift_adjustment
    return compensated_raw * multiplier


def compute_weight_stability(logs, calibration, settings):
    weights = []
    for log in logs[-8:]:
        weight = calculate_weight_grams(log.raw_adc, log.temp_1, calibration, settings)
        if weight is not None:
            weights.append(weight)

    if not weights:
        return {
            "progress": 0,
            "stable": False,
            "stable_weight": None,
            "ema_weight": None,
            "samples": 0,
        }

    live_weight = weights[-1]
    if abs(live_weight) <= AUTO_ZERO_GRAMS:
        live_weight = 0.0

    return {
        "progress": 100,
        "stable": True,
        "stable_weight": round(live_weight, 2),
        "ema_weight": round(live_weight, 2),
        "samples": len(weights),
    }


def mean_or_none(values):
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return mean(clean)
