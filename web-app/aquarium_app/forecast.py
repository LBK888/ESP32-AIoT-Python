from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import sqrt
from typing import Any

from .store import parse_time


def linear_forecast(
    readings: list[dict[str, Any]],
    *,
    horizon_minutes: int = 30,
) -> dict[str, Any]:
    numeric = [item for item in readings if item.get("value") is not None]
    if len(numeric) < 3:
        return {
            "available": False,
            "reason": "至少需要三筆數值資料",
            "horizon_minutes": horizon_minutes,
            "points": [],
        }

    times = [parse_time(item["recorded_at"]).timestamp() for item in numeric]
    values = [float(item["value"]) for item in numeric]
    origin = times[0]
    xs = [(value - origin) / 60 for value in times]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(values) / len(values)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    slope = 0.0 if denominator == 0 else sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values)) / denominator
    intercept = y_mean - slope * x_mean
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, values)]
    rmse = sqrt(sum(value * value for value in residuals) / len(residuals))
    last_time = datetime.fromtimestamp(times[-1], UTC)
    last_x = xs[-1]
    steps = max(2, min(12, horizon_minutes // 5 + 1))
    points = []
    for index in range(steps):
        minutes = horizon_minutes * index / (steps - 1)
        predicted = intercept + slope * (last_x + minutes)
        points.append(
            {
                "at": (last_time + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
                "value": round(predicted, 4),
                "lower": round(predicted - 1.96 * rmse, 4),
                "upper": round(predicted + 1.96 * rmse, 4),
            }
        )
    confidence = max(0.0, min(1.0, 1 / (1 + rmse)))
    return {
        "available": True,
        "method": "linear-regression-v1",
        "control_isolated": True,
        "samples": len(numeric),
        "horizon_minutes": horizon_minutes,
        "slope_per_hour": round(slope * 60, 4),
        "rmse": round(rmse, 4),
        "confidence": round(confidence, 3),
        "points": points,
    }

