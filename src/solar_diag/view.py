"""Aktuální obraz baterie. Stará měření se sem jako živá čísla nedostanou."""

from __future__ import annotations

from datetime import datetime

from solar_diag.storage import iso, load_ts

MEASUREMENT_KEYS = (
    "mode",
    "mode_label",
    "soc",
    "soh",
    "voltage_v",
    "current_a",
    "power_w",
    "bms_temp_c",
    "cycle_count",
    "charge_cutoff_v",
    "discharge_cutoff_v",
    "charge_limit_a",
    "discharge_limit_a",
    "max_cell_mv",
    "min_cell_mv",
    "max_cell_index",
    "min_cell_index",
    "cell_delta_mv",
    "max_cell_temp_c",
    "min_cell_temp_c",
    "remaining_wh",
    "charged_today_wh",
    "discharged_today_wh",
    "state_bits",
    "protection_bits",
    "alarm_bits",
    "fault_bits",
)
LIST_KEYS = ("modules", "cells", "alarms", "notices", "quality_notes")


def empty_battery(row: dict, error: str, last_success_at: datetime | None = None) -> dict:
    view = {
        "id": row["id"],
        "name": row.get("name") or f"Force H2 {row['ip']}",
        "ip": row["ip"],
        "logger_serial": row.get("logger_serial") or 0,
        "mac": row.get("mac"),
        "manufacturer": row.get("manufacturer"),
        "model": row.get("model"),
        "firmware": row.get("firmware"),
        "bms_serial": row.get("bms_serial"),
        "module_count": row.get("module_count"),
        "cell_count": row.get("cell_count"),
        "communication_ok": False,
        "error": error,
        "measured_at": None,
        "last_success_at": iso(last_success_at) if last_success_at else row.get("last_seen"),
        "age_seconds": None,
        "quality_ok": None,
    }
    for key in MEASUREMENT_KEYS:
        view[key] = None
    for key in LIST_KEYS:
        view[key] = []
    return view


def live_battery(row: dict, reading: dict, measured_at: datetime, last_success_at: datetime | None) -> dict:
    view = empty_battery(row, "", last_success_at)
    view["communication_ok"] = True
    view["error"] = None
    view["measured_at"] = iso(measured_at)
    view["last_success_at"] = iso(measured_at)
    view["quality_ok"] = bool(reading.get("quality_ok"))
    view["manufacturer"] = reading.get("manufacturer") or view["manufacturer"]
    view["model"] = reading.get("model") or view["model"]
    view["firmware"] = reading.get("firmware") or view["firmware"]
    view["bms_serial"] = reading.get("bms_serial") or view["bms_serial"]
    if reading.get("module_count") is not None:
        view["module_count"] = reading.get("module_count")
    if reading.get("cell_count") is not None:
        view["cell_count"] = reading.get("cell_count")
    for key in MEASUREMENT_KEYS:
        if key in reading:
            view[key] = reading.get(key)
    for key in LIST_KEYS:
        view[key] = reading.get(key) or []
    return view


def apply_freshness(battery: dict, now: datetime, stale_after: float) -> dict:
    """Když je odpověď stará, čísla zmizí. Čas posledního úspěchu zůstane."""
    if not battery.get("communication_ok"):
        return battery
    measured = load_ts(battery.get("measured_at"))
    if measured is None:
        return empty_battery(battery, "chybí čas měření", load_ts(battery.get("last_success_at")))
    age = (now - measured).total_seconds()
    if age <= stale_after:
        fresh = dict(battery)
        fresh["age_seconds"] = max(0, int(age))
        return fresh
    stale = empty_battery(
        battery,
        "poslední odpověď je stará, neukazuji ji jako aktuální stav",
        measured,
    )
    stale["age_seconds"] = int(age)
    return stale
