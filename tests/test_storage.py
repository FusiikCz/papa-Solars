from datetime import timedelta

from solar_diag.collector import _snapshot
from solar_diag.storage import Store, utcnow


def test_sqlite_keeps_history_and_separates_outages(tmp_path):
    store = Store("sqlite:///" + str(tmp_path / "diag.db"))
    store.init()
    row = store.upsert_battery(
        ip="192.168.99.20",
        logger_serial=99,
        mac="AA",
        name="Dům",
        manufacturer="Pylon",
        model="Force_H2",
        firmware="V2.0",
        bms_serial="ABC",
        module_count=1,
        cell_count=2,
        seen=utcnow(),
    )
    moment = utcnow()
    reading = {
        "soc": 80,
        "soh": 97,
        "voltage_v": 400.0,
        "current_a": 1.5,
        "power_w": 600.0,
        "bms_temp_c": 26.0,
        "cycle_count": 3,
        "cell_delta_mv": 10,
        "min_cell_mv": 3300,
        "max_cell_mv": 3310,
        "remaining_wh": 1000,
        "charged_today_wh": 100,
        "discharged_today_wh": 50,
        "mode": "charge",
        "quality_ok": True,
        "modules": [],
        "cells": [
            {"index": 0, "module": 0, "cell": 0, "mv": 3300},
            {"index": 1, "module": 0, "cell": 1, "mv": 3310},
        ],
        "alarms": [{"level": "alarm", "text": "Výstraha: vysoké napětí článku"}],
        "notices": [],
        "quality_notes": [],
    }
    store.insert_snapshot(_snapshot(row["id"], moment, reading, None))
    store.insert_snapshot(_snapshot(row["id"], moment + timedelta(seconds=30), None, "neodpověděl"))

    history = store.history(row["id"], moment - timedelta(minutes=5))
    assert [point["soc"] for point in history] == [80]
    events = store.events(row["id"], moment - timedelta(minutes=5))
    assert len(events) == 2
    assert events[0]["online"] is False
    assert events[0]["error"] == "neodpověděl"
    assert store.last_success(row["id"]) == moment.replace(microsecond=0)
    series = store.cell_history(row["id"], 1, moment - timedelta(minutes=5))
    assert series == [{"t": series[0]["t"], "mv": 3310}]
    assert store.cell_history(row["id"], 4, moment - timedelta(minutes=5)) == []
    store.close()
