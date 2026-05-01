from __future__ import annotations

import math
from datetime import datetime
from statistics import mean, pstdev
from typing import List, Optional


def dew_point_celsius(t_c: float, rh_percent: float) -> float:
    """Estimate dew point (C) from temperature (C) and relative humidity (%) using Magnus formula."""
    a, b = 17.27, 237.7
    rh = max(min(rh_percent, 100.0), 0.01)
    alpha = (a * t_c) / (b + t_c) + math.log(rh / 100.0)
    return (b * alpha) / (a - alpha)


def absolute_humidity_gm3(t_c: float, rh_percent: float) -> float:
    """Return absolute humidity in g/m^3 for given temp (C) and RH (%).

    Formula based on ideal gas relation for water vapor.
    """
    # Saturation vapor pressure over water (hPa) using Magnus-Tetens
    sat_vap_hpa = 6.112 * math.exp((17.62 * t_c) / (243.12 + t_c))
    vapor_pressure_hpa = (max(min(rh_percent, 100.0), 0.0) / 100.0) * sat_vap_hpa
    # AH = 216.7 * (e / (T_K)) where e in hPa and T_K in K
    ah = 216.7 * (vapor_pressure_hpa / (273.15 + t_c))
    return ah


def ema_series(values: List[float], alpha: float = 0.2) -> List[float]:
    """Compute exponential moving average series for a list of values."""
    if not values:
        return []
    out: List[float] = [values[0]]
    for v in values[1:]:
        out.append((alpha * v) + (1 - alpha) * out[-1])
    return out


def robust_hourly_slope(times: List[datetime], values: List[float], min_points: int = 3) -> Optional[float]:
    """Estimate slope (units per hour) using least-squares with simple sigma-clipping.

    Returns None if not enough data or degenerate.
    """
    if not times or not values or len(times) < min_points:
        return None

    # Convert to hours since first timestamp
    t0 = times[0].timestamp()
    xs = [(t.timestamp() - t0) / 3600.0 for t in times]
    ys = list(values)

    # Iterative sigma-clipping
    for _ in range(3):
        n = len(xs)
        if n < min_points:
            return None
        mx = mean(xs)
        my = mean(ys)
        denom = sum((x - mx) ** 2 for x in xs)
        if denom == 0:
            return None
        numer = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
        m = numer / denom
        # residuals
        res = [ys[i] - (m * xs[i] + (my - m * mx)) for i in range(n)]
        sigma = pstdev(res) if n > 1 else 0.0
        if sigma <= 1e-6:
            return float(m)
        # keep points within 2.5 sigma
        keep_mask = [abs(r) <= 2.5 * sigma for r in res]
        if all(keep_mask):
            return float(m)
        xs = [x for i, x in enumerate(xs) if keep_mask[i]]
        ys = [y for i, y in enumerate(ys) if keep_mask[i]]

    # final slope
    n = len(xs)
    if n < min_points:
        return None
    mx = mean(xs)
    my = mean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    numer = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    return float(numer / denom)
