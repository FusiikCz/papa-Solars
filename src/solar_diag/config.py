"""Volitelný seznam loggerů. Síť se z konfigurace změnit nedá."""

from __future__ import annotations

from pathlib import Path

import yaml

from solar_diag.network import SOLAR_SUBNET, OutsideSolarNetwork, assert_solar_host


def load_config(path: Path) -> tuple[list[dict], list[str]]:
    if not path.exists():
        return [], []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return [], ["config.yaml musí být mapa s klíčem devices"]

    errors: list[str] = []
    requested = raw.get("subnet")
    if requested is not None and str(requested).strip() != SOLAR_SUBNET:
        errors.append(
            f"Síť {requested} se ignoruje. Sběr zůstává na {SOLAR_SUBNET}."
        )

    devices: list[dict] = []
    entries = raw.get("devices") or []
    if not isinstance(entries, list):
        return [], errors + ["devices musí být seznam"]

    for item in entries:
        if not isinstance(item, dict) or "ip" not in item:
            errors.append("Položka v devices nemá ip")
            continue
        ip = str(item["ip"]).strip()
        try:
            assert_solar_host(ip)
        except OutsideSolarNetwork as exc:
            errors.append(str(exc))
            continue
        serial_raw = item.get("serial") or 0
        try:
            serial = int(serial_raw)
        except (TypeError, ValueError):
            errors.append(f"{ip}: sériové číslo {serial_raw} není číslo")
            continue
        name = str(item["name"]).strip() if item.get("name") else None
        devices.append({"ip": ip, "serial": serial, "name": name})
    return devices, errors
