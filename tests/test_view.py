from datetime import datetime, timedelta, timezone

from solar_diag.view import apply_freshness, live_battery


def test_stale_reading_is_not_presented_as_current():
    moment = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
    row = {
        "id": 1,
        "name": "Dům",
        "ip": "192.168.99.20",
        "logger_serial": 99,
        "mac": None,
        "manufacturer": "Pylon",
        "model": "Force_H2",
        "firmware": "V2.0",
        "bms_serial": "ABC",
        "last_seen": None,
    }
    reading = {
        "soc": 80,
        "voltage_v": 400.0,
        "quality_ok": True,
        "modules": [{"index": 0, "voltage_v": 100.0, "temp_c": 25.0}],
        "cells": [{"index": 0, "module": 0, "cell": 0, "mv": 3300}],
        "alarms": [],
        "notices": [],
        "quality_notes": [],
    }
    live = live_battery(row, reading, moment, moment)
    fresh = apply_freshness(live, moment + timedelta(seconds=10), 75)
    assert fresh["communication_ok"] is True
    assert fresh["soc"] == 80

    stale = apply_freshness(live, moment + timedelta(seconds=120), 75)
    assert stale["communication_ok"] is False
    assert stale["soc"] is None
    assert stale["voltage_v"] is None
    assert stale["cells"] == []
    assert stale["last_success_at"].startswith("2026-11-15T12:00:00")
