"""Dekódování mapy Pylontech Force H2.

Mapa vychází z registrů Force H2 (okna 0x1000 a 0x1400). Významy bitů
jsou pojmenované podle té mapy. Vlastní prahy napětí a teploty tu nejsou:
ochranu hlásí samotná BMS.
"""

from __future__ import annotations

import re

CELLS_PER_MODULE = 30
MAX_MODULES = 6
MAX_CELLS = 150

PROTECTION_BITS = {
    15: "Ochrana: vypínací napětí modulu",
    14: "Ochrana: přepětí článku",
    13: "Ochrana: podpětí článku",
    12: "Ochrana: přehřátí stacku nebo článku",
    11: None,
    10: "Ochrana: zkrat",
    9: "Ochrana: vybíjecí nadproud",
    8: "Ochrana: nabíjecí nadproud",
    7: "Ochrana: přehřátí modulu",
    6: "Ochrana: podchlazení modulu",
    5: "Ochrana: přehřátí modulu",
    4: "Ochrana: podchlazení modulu",
    3: "Ochrana: přepětí stacku",
    2: "Ochrana: podpětí stacku",
    1: "Ochrana: přepětí modulu",
    0: "Ochrana: podpětí modulu",
}

ALARM_BITS = {
    15: None,
    14: "Výstraha: vysoké napětí článku",
    13: "Výstraha: nízké napětí článku",
    12: "Výstraha: vysoká teplota článku",
    11: "Výstraha: vysoká teplota stacku",
    10: None,
    9: "Výstraha: vybíjecí nadproud",
    8: "Výstraha: nabíjecí nadproud",
    7: "Výstraha: vysoká teplota modulu",
    6: "Výstraha: nízká teplota modulu",
    5: "Výstraha: vysoká teplota modulu",
    4: "Výstraha: nízká teplota modulu",
    3: "Výstraha: vysoké napětí stacku",
    2: "Výstraha: nízké napětí stacku",
    1: "Výstraha: vysoké napětí modulu",
    0: "Výstraha: nízké napětí modulu",
}

FAULT_BITS = {
    10: "Porucha: nesoulad při inicializaci",
    9: "Porucha: chyba I2C",
    8: "Porucha: chyba obvodu monitoru baterie",
    7: "Porucha: zkrat",
    6: "Porucha: poškozená baterie",
    5: "Porucha: relé",
    4: "Porucha: obrácená polarita",
    3: "Porucha: DC přepětí",
    2: "Porucha: modul je offline",
    1: "Porucha: chyba měření teploty",
    0: "Porucha: chyba měření napětí",
}

MODE_LABELS = {
    "charge": "nabíjení",
    "discharge": "vybíjení",
    "idle": "klid",
    "sleep": "spánek",
    "unknown": "neurčeno",
}


def identify(regs: dict[int, int]) -> dict:
    manufacturer = _ascii(regs, 0x1000, 5)
    model = _ascii(regs, 0x1005, 5)
    return {
        "manufacturer": manufacturer,
        "model": model,
        "firmware": _firmware(regs),
        "is_force_h2": is_force_h2(manufacturer, model),
    }


def is_force_h2(manufacturer: str | None, model: str | None) -> bool:
    model_key = re.sub(r"[^a-z0-9]", "", (model or "").lower())
    return "forceh2" in model_key


def _u16(regs: dict[int, int], addr: int) -> int | None:
    return regs.get(addr)


def _i16(regs: dict[int, int], addr: int) -> int | None:
    value = regs.get(addr)
    if value is None:
        return None
    return value - 0x10000 if value >= 0x8000 else value


def _u32(regs: dict[int, int], addr: int) -> int | None:
    high, low = regs.get(addr), regs.get(addr + 1)
    if high is None or low is None:
        return None
    return (high << 16) | low


def _i32(regs: dict[int, int], addr: int) -> int | None:
    value = _u32(regs, addr)
    if value is None:
        return None
    return value - 0x100000000 if value >= 0x80000000 else value


def _ascii(regs: dict[int, int], start: int, count: int) -> str | None:
    raw = bytearray()
    for offset in range(count):
        word = regs.get(start + offset)
        if word is None:
            return None
        raw.append((word >> 8) & 0xFF)
        raw.append(word & 0xFF)
    text = raw.split(b"\x00", 1)[0].decode("ascii", errors="ignore")
    text = "".join(ch for ch in text if ch.isprintable()).strip()
    return text or None


def _scale(value: int | None, factor: float, digits: int) -> float | None:
    if value is None:
        return None
    return round(value * factor, digits)


def _firmware(regs: dict[int, int]) -> str | None:
    version = _u16(regs, 0x100A)
    if version is None:
        return None
    text = f"V{version >> 8}.{version & 0xFF}"
    build = _u16(regs, 0x100B)
    if build:
        text += f" B{build >> 8}.{build & 0xFF}"
    return text


def mode_from_state(state: int | None) -> str:
    if state is None:
        return "unknown"
    if state & (1 << 13):
        return "sleep"
    charging = bool(state & (1 << 11))
    discharging = bool(state & (1 << 12))
    if charging and not discharging:
        return "charge"
    if discharging and not charging:
        return "discharge"
    if state & (1 << 10):
        return "idle"
    return "unknown"


def _named_bits(value: int | None, table: dict[int, str | None], register: str) -> list[dict]:
    if value is None:
        return []
    items = []
    for bit in range(16):
        if not value & (1 << bit):
            continue
        label = table.get(bit)
        if label:
            items.append({"level": _level(register), "text": label})
        elif bit not in table:
            items.append(
                {
                    "level": "info",
                    "text": f"Bit {bit} v {register} je nastavený a mapa registrů ho nepojmenovává",
                }
            )
    return items


def _level(register: str) -> str:
    if register == "ochranách":
        return "protection"
    if register == "výstrahách":
        return "alarm"
    return "fault"


def _unique(items: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out = []
    for item in items:
        key = (item["level"], item["text"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def decode(regs: dict[int, int]) -> dict:
    """Převede slovník adresa→hodnota na jedno čtení. Nic si nedomýšlí z minula."""
    notes: list[str] = []
    if 0x1403 not in regs and 0x1407 not in regs:
        return {
            "decoded": False,
            "is_force_h2": False,
            "error": "stavové registry nepřišly",
            "quality_ok": False,
            "quality_notes": ["stavové registry nepřišly"],
            "alarms": [],
            "notices": [],
            "modules": [],
            "cells": [],
        }

    manufacturer = _ascii(regs, 0x1000, 5)
    model = _ascii(regs, 0x1005, 5)
    state = _u16(regs, 0x1400)
    mode = mode_from_state(state)
    voltage_v = _scale(_u16(regs, 0x1403), 0.1, 1)
    current_a = _scale(_i32(regs, 0x1404), 0.01, 2)
    soc = _u16(regs, 0x1407)
    soh = _u16(regs, 0x1420)
    max_cell = _u16(regs, 0x1410)
    min_cell = _u16(regs, 0x1411)
    module_count = _u16(regs, 0x1436)
    cell_count = _u16(regs, 0x1437)

    modules = []
    module_n = module_count if module_count is not None else 0
    if module_n > MAX_MODULES:
        notes.append(f"Počet modulů {module_n} je mimo mapu Force H2 (max {MAX_MODULES}).")
        module_n = 0
    for index in range(module_n):
        modules.append(
            {
                "index": index,
                "voltage_v": _scale(_u16(regs, 0x1460 + index), 0.01, 2),
                "temp_c": _scale(_i16(regs, 0x14B0 + index), 0.1, 1),
            }
        )

    cells = []
    cell_n = cell_count if cell_count is not None else 0
    if cell_n > MAX_CELLS:
        notes.append(f"Počet článků {cell_n} je mimo mapu Force H2 (max {MAX_CELLS}).")
        cell_n = 0
    elif cell_n == 0:
        notes.append("BMS hlásí 0 článků, napětí jednotlivých článků proto nečtu.")
    for index in range(cell_n):
        mv = _u16(regs, 0x1500 + index)
        if mv is None:
            notes.append(f"Chybí napětí článku {index}.")
            break
        cells.append(
            {
                "index": index,
                "module": index // CELLS_PER_MODULE,
                "cell": index % CELLS_PER_MODULE,
                "mv": mv,
            }
        )

    alarms: list[dict] = []
    alarms += _named_bits(_u16(regs, 0x1401), PROTECTION_BITS, "ochranách")
    alarms += _named_bits(_u16(regs, 0x1402), ALARM_BITS, "výstrahách")
    alarms += _named_bits(_u16(regs, 0x1433), FAULT_BITS, "poruchách")
    if state is not None and state & (1 << 3):
        alarms.append({"level": "fault", "text": "BMS hlásí poruchu"})
    latched = _u16(regs, 0x140F)
    if latched is not None and latched & (1 << 3):
        alarms.append({"level": "fault", "text": "Porucha: relé"})
    if latched is not None:
        for bit in (4, 5, 6):
            if latched & (1 << bit):
                alarms.append(
                    {
                        "level": "info",
                        "text": f"Nerozpoznaný příznak BMS (registr 0x140F bit {bit})",
                    }
                )
    alarms = _unique(alarms)

    notices = []
    if _u16(regs, 0x142F) == 1:
        notices.append("BMS žádá vynucené nabíjení")
    if _u16(regs, 0x1430) == 1:
        notices.append("BMS žádá balanční nabíjení")
    if _u16(regs, 0x1438) == 1:
        notices.append("Nabíjení není dovolené")
    if _u16(regs, 0x1439) == 1:
        notices.append("Vybíjení není dovolené")

    if soc is not None and not 0 <= soc <= 100:
        notes.append(f"SOC {soc} nesedí do 0–100 %. Beru to jako chybu čtení.")
    if soh is not None and not 0 <= soh <= 100:
        notes.append(f"SOH {soh} nesedí do 0–100 %. Beru to jako chybu čtení.")
    if voltage_v is not None and not 0 <= voltage_v <= 800:
        notes.append(f"Napětí stacku {voltage_v} V nedává u Force H2 smysl.")
    if current_a is not None and abs(current_a) > 500:
        notes.append(f"Proud {current_a} A nedává u Force H2 smysl.")
    weird_cells = [c["index"] for c in cells if c["mv"] < 2000 or c["mv"] > 4500]
    if weird_cells:
        notes.append(
            "Některé články jsou mimo 2000–4500 mV. U LFP to bývá prázdný registr nebo špatné čtení, ne mez ochrany."
        )
    populated = [c["mv"] for c in cells if c["mv"] >= 2000]
    if populated and max_cell is not None and min_cell is not None:
        if max(populated) != max_cell or min(populated) != min_cell:
            notes.append("Min/max z registrů BMS nesedí s výpisem článků.")
    if current_a is not None and mode == "charge" and current_a < -0.5:
        notes.append("Znaménko proudu nesedí se stavem BMS (nabíjení).")
    if current_a is not None and mode == "discharge" and current_a > 0.5:
        notes.append("Znaménko proudu nesedí se stavem BMS (vybíjení).")

    power_w = None
    if voltage_v is not None and current_a is not None:
        power_w = round(voltage_v * current_a, 1)
    delta = None
    if max_cell is not None and min_cell is not None:
        delta = max_cell - min_cell

    return {
        "decoded": True,
        "is_force_h2": is_force_h2(manufacturer, model),
        "manufacturer": manufacturer,
        "model": model,
        "firmware": _firmware(regs),
        "bms_serial": _ascii(regs, 0x1450, 16),
        "module_count": module_count,
        "cell_count": cell_count,
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "soc": soc,
        "soh": soh,
        "voltage_v": voltage_v,
        "current_a": current_a,
        "power_w": power_w,
        "bms_temp_c": _scale(_i16(regs, 0x1406), 0.1, 1),
        "cycle_count": _u16(regs, 0x1408),
        "charge_cutoff_v": _scale(_u16(regs, 0x1409), 0.1, 1),
        "discharge_cutoff_v": _scale(_u16(regs, 0x140C), 0.1, 1),
        "charge_limit_a": _scale(_i32(regs, 0x140A), 0.01, 2),
        "discharge_limit_a": _scale(_i32(regs, 0x140D), 0.01, 2),
        "max_cell_mv": max_cell,
        "min_cell_mv": min_cell,
        "max_cell_index": _u16(regs, 0x1412),
        "min_cell_index": _u16(regs, 0x1413),
        "cell_delta_mv": delta,
        "max_cell_temp_c": _scale(_i16(regs, 0x1414), 0.1, 1),
        "min_cell_temp_c": _scale(_i16(regs, 0x1415), 0.1, 1),
        "remaining_wh": _u32(regs, 0x1421),
        "charged_today_wh": _u32(regs, 0x1427),
        "discharged_today_wh": _u32(regs, 0x1429),
        "modules": modules,
        "cells": cells,
        "alarms": alarms,
        "notices": notices,
        "quality_ok": not notes,
        "quality_notes": notes,
        "state_bits": state,
        "protection_bits": _u16(regs, 0x1401),
        "alarm_bits": _u16(regs, 0x1402),
        "fault_bits": _u16(regs, 0x1433),
    }
