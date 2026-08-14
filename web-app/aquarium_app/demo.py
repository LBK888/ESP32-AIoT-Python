from __future__ import annotations

import math
from datetime import timedelta

from .store import Store, iso, utc_now


def seed_demo(store: Store) -> dict[str, int]:
    """Insert deterministic, explicitly labelled demonstration data."""
    store.initialize()
    now = utc_now()
    inserted = 0
    series = {
        "temp-01": ("temp_c", "°C", lambda index: 26.1 + math.sin(index / 6) * 0.55),
        "level-01": ("level_pct", "%", lambda index: 82 - index * 0.08),
        "quality-01": ("water_quality_score", "/100", lambda index: 90 - math.sin(index / 5) * 2.2),
        "air-01": ("oxygen_risk", "%", lambda index: 16 + math.sin(index / 4) * 5.5),
    }
    for device_id, (metric, unit, value_fn) in series.items():
        for index in range(48):
            value = round(value_fn(index), 2)
            status = "warning" if metric == "oxygen_risk" and value > 19 else "normal"
            inserted += store.ingest_readings(
                device_id,
                [{"metric": metric, "value": value, "unit": unit, "status": status}],
                iso(now - timedelta(minutes=(47 - index) * 30)),
                {"source": "demo", "deterministic": True},
            )
    store.create_event(
        device_id="feed-01",
        event_type="feeding.completed",
        severity="info",
        title="餵食完成",
        detail="示範資料：裝置已回報餵食流程完成。",
        occurred_at=iso(now - timedelta(hours=2)),
        source="demo",
        payload={"source": "demo"},
    )
    store.create_event(
        device_id="light-01",
        event_type="lighting.schedule",
        severity="info",
        title="關閉日間照明",
        detail="示範資料：預定照明排程。",
        occurred_at=iso(now),
        scheduled_for=iso(now + timedelta(hours=3)),
        source="demo",
        payload={"source": "demo"},
    )
    return {"readings": inserted, "events": 2}

