"""Sběr. Každý cíl projde assertem, že leží v 192.168.99.0/24."""

from __future__ import annotations

import asyncio
import errno
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from solar_diag.config import load_config
from solar_diag.discover import link_status, tcp_scan, udp_discover
from solar_diag.network import SOLAR_SUBNET, assert_solar_host
from solar_diag.protocol import ModbusError, ProtocolError, SolarmanClient
from solar_diag.registers import decode, identify
from solar_diag.storage import SNAPSHOT_COLUMNS, Store, iso, utcnow
from solar_diag.view import apply_freshness, empty_battery, live_battery

log = logging.getLogger(__name__)

READ_PLAN = (
    (0x1000, 13, False),
    (0x1400, 58, True),
    (0x1450, 16, False),
    (0x1460, 86, False),
)


def friendly(ip: str, exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return f"{ip} neodpověděl"
    if isinstance(exc, OSError):
        code = exc.errno or getattr(exc, "winerror", None)
        if code in {errno.ECONNREFUSED, 10061}:
            return f"{ip}: port 8899 odmítl spojení"
        if code in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EHOSTDOWN, 10051, 10065, 10064}:
            return f"{ip}: síť {SOLAR_SUBNET} teď není dostupná"
        if code in {errno.ETIMEDOUT, 10060}:
            return f"{ip} neodpověděl"
        return f"{ip}: {exc.strerror or exc}"
    if isinstance(exc, (ProtocolError, ModbusError)):
        return f"{ip}: {exc}"
    return f"{ip}: {exc}"


def read_registers(client: SolarmanClient) -> tuple[dict[int, int], list[str]]:
    regs: dict[int, int] = {}
    errors: list[str] = []
    for address, quantity, mandatory in READ_PLAN:
        try:
            words = client.read_holding(address, quantity)
        except Exception as exc:
            if mandatory:
                raise
            errors.append(friendly(client.ip, exc))
            continue
        for offset, word in enumerate(words):
            regs[address + offset] = word
    cell_count = regs.get(0x1437, 0)
    if not 0 < cell_count <= 150:
        return regs, errors
    address = 0x1500
    left = cell_count
    while left:
        quantity = min(125, left)
        try:
            words = client.read_holding(address, quantity)
        except Exception as exc:
            errors.append(friendly(client.ip, exc))
            break
        for offset, word in enumerate(words):
            regs[address + offset] = word
        address += quantity
        left -= quantity
    return regs, errors


def _identify(item: dict) -> dict:
    ip = str(assert_solar_host(item["ip"]))
    serial = int(item.get("serial") or 0)
    try:
        with SolarmanClient(ip, serial, timeout=3) as client:
            words = client.read_holding(0x1000, 13)
            serial = client.serial or serial
        regs = {0x1000 + offset: word for offset, word in enumerate(words)}
        found = identify(regs)
        return {"ip": ip, "serial": serial, "mac": item.get("mac"), "name": item.get("name"), **found}
    except Exception as exc:
        return {
            "ip": ip,
            "serial": serial,
            "mac": item.get("mac"),
            "name": item.get("name"),
            "error": friendly(ip, exc),
            "is_force_h2": False,
            "model": None,
            "manufacturer": None,
            "firmware": None,
        }


def _read_battery(item: dict) -> dict:
    ip = str(assert_solar_host(item["ip"]))
    serial = int(item.get("serial") or 0)
    base = {"ip": ip, "serial": serial, "mac": item.get("mac"), "name": item.get("name")}
    try:
        with SolarmanClient(ip, serial) as client:
            regs, errors = read_registers(client)
            serial = client.serial or serial
        reading = decode(regs)
        if errors:
            reading["quality_ok"] = False
            reading["quality_notes"] = [*reading.get("quality_notes", []), *errors]
        base["serial"] = serial
        if not reading.get("decoded"):
            return {**base, "ok": False, "error": reading.get("error") or "stavové registry nepřišly"}
        model_known = bool(reading.get("model"))
        accepted = reading.get("is_force_h2") or item.get("known") or item.get("configured")
        if model_known and not reading.get("is_force_h2") and not item.get("known"):
            accepted = False
        if not accepted:
            return {
                **base,
                "ok": False,
                "other": True,
                "model": reading.get("model"),
                "error": f"nalezeno {reading.get('model') or 'zařízení'}, není to Force H2",
            }
        if model_known and not reading.get("is_force_h2"):
            reading["quality_ok"] = False
            reading["quality_notes"] = [
                *reading.get("quality_notes", []),
                "Model teď není Force H2, data ukládám, protože zařízení už v diagnostice je.",
            ]
        return {**base, "ok": True, "reading": reading}
    except Exception as exc:
        return {**base, "ok": False, "error": friendly(ip, exc)}


def _snapshot(battery_id: int, ts: datetime, reading: dict | None, error: str | None) -> dict:
    row = {column: None for column in SNAPSHOT_COLUMNS}
    row.update(
        {
            "battery_id": battery_id,
            "ts": ts,
            "online": reading is not None,
            "error": error,
            "has_alarm": False,
            "quality_ok": False,
            "modules": [],
            "cells": [],
            "alarms": [],
            "notices": [],
            "quality_notes": [],
        }
    )
    if reading is None:
        return row
    for column in SNAPSHOT_COLUMNS:
        if column in reading:
            row[column] = reading[column]
    row["battery_id"] = battery_id
    row["ts"] = ts
    row["online"] = True
    row["error"] = None
    row["has_alarm"] = bool(reading.get("alarms"))
    row["quality_ok"] = bool(reading.get("quality_ok"))
    return row


class Hub:
    def __init__(self, store: Store, devices: list[dict], config_errors: list[str], poll_seconds: int, discovery_seconds: int):
        self.store = store
        self.devices = devices
        self.config_errors = config_errors
        self.poll_seconds = poll_seconds
        self.discovery_seconds = discovery_seconds
        self.batteries: dict[int, dict] = {}
        self.other: list[dict] = []
        self.candidates: dict[str, dict] = {}
        self.meta: dict = {"phase": "start", "open_8899": 0}
        self._listeners: list[asyncio.Queue] = []
        self._next_discovery = 0.0

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._listeners.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._listeners:
            self._listeners.remove(queue)

    def public_state(self) -> dict:
        now = utcnow()
        stale_after = self.poll_seconds * 2 + 15
        batteries = [
            apply_freshness(battery, now, stale_after) for battery in self.batteries.values()
        ]
        batteries.sort(key=lambda item: (item["ip"], item.get("logger_serial") or 0))
        return {
            "subnet": SOLAR_SUBNET,
            "on_link": self.meta.get("on_link"),
            "source_ip": self.meta.get("source_ip"),
            "phase": self.meta.get("phase", "start"),
            "last_discovery_at": self.meta.get("last_discovery_at"),
            "last_poll_at": self.meta.get("last_poll_at"),
            "open_8899": self.meta.get("open_8899", 0),
            "poll_seconds": self.poll_seconds,
            "discovery_seconds": self.discovery_seconds,
            "config_errors": self.config_errors,
            "batteries": batteries,
            "other_loggers": self.other,
        }

    async def publish(self) -> None:
        payload = self.public_state()
        for queue in list(self._listeners):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(payload)

    def load_known(self) -> None:
        for row in self.store.list_batteries():
            last = self.store.last_success(row["id"])
            self.batteries[row["id"]] = empty_battery(
                row, "čekám na první čtení v tomto běhu", last
            )

    async def run(self) -> None:
        self.load_known()
        self.meta.update(link_status())
        log.info("Sběr je uzamčen na %s", SOLAR_SUBNET)
        if self.meta.get("on_link"):
            log.info("Počítač je v solární síti jako %s", self.meta.get("source_ip"))
        else:
            log.warning(
                "Tenhle počítač nemá adresu v %s. Ptám se jen tam, zdrojová adresa je %s.",
                SOLAR_SUBNET,
                self.meta.get("source_ip") or "žádná",
            )
        for error in self.config_errors:
            log.warning("Konfigurace: %s", error)
        await self.publish()
        while True:
            started = time.monotonic()
            try:
                if started >= self._next_discovery:
                    await self.discover()
                    self._next_discovery = time.monotonic() + self.discovery_seconds
                await self.poll()
                self.meta["phase"] = "ok"
                self.meta["last_poll_at"] = iso(utcnow())
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("cyklus sběru selhal")
                self.meta["phase"] = "error"
            await self.publish()
            rest = self.poll_seconds - (time.monotonic() - started)
            await asyncio.sleep(max(1, rest))

    async def discover(self) -> None:
        self.meta["phase"] = "discovery"
        self.meta.update(link_status())
        await self.publish()
        static_ips = [device["ip"] for device in self.devices]
        udp, open_ips = await asyncio.gather(
            asyncio.to_thread(udp_discover, static_ips),
            tcp_scan(),
        )
        found: dict[str, dict] = {item["ip"]: item for item in udp}
        for ip in open_ips:
            found.setdefault(ip, {"ip": ip, "mac": None, "serial": 0})
        for device in self.devices:
            current = found.get(device["ip"], {"ip": device["ip"], "mac": None, "serial": 0})
            if device["serial"]:
                current["serial"] = device["serial"]
            current["name"] = device["name"]
            current["configured"] = True
            found[device["ip"]] = current

        sem = asyncio.Semaphore(4)

        async def one(item: dict) -> dict:
            async with sem:
                return await asyncio.to_thread(_identify, item)

        identified = await asyncio.gather(*(one(item) for item in found.values()))
        for item in identified:
            previous = found[item["ip"]]
            serial = item.get("serial") or previous.get("serial") or 0
            found[item["ip"]] = {**previous, **item, "serial": serial}
        self.candidates = found
        self.meta["open_8899"] = len(open_ips)
        self.meta["last_discovery_at"] = iso(utcnow())
        log.info(
            "Prohledáno %s: UDP odpovědí %s, otevřený port 8899 na %s adresách",
            SOLAR_SUBNET,
            len(udp),
            len(open_ips),
        )

    async def poll(self) -> None:
        targets: dict[str, dict] = {}
        for row in self.store.list_batteries():
            targets[row["ip"]] = {
                "ip": row["ip"],
                "serial": int(row["logger_serial"] or 0),
                "mac": row.get("mac"),
                "name": None,
                "known": True,
                "is_force_h2": True,
            }
        for item in self.candidates.values():
            if not (item.get("is_force_h2") or item.get("configured")):
                continue
            current = targets.get(item["ip"], {})
            serial = int(item.get("serial") or 0) or int(current.get("serial") or 0)
            targets[item["ip"]] = {
                **current,
                **item,
                "serial": serial,
                "known": current.get("known", False),
                "configured": item.get("configured", current.get("configured", False)),
            }
        for device in self.devices:
            current = targets.get(device["ip"], {})
            serial = int(device["serial"] or 0) or int(current.get("serial") or 0)
            targets[device["ip"]] = {
                **current,
                "ip": device["ip"],
                "serial": serial,
                "name": device["name"],
                "configured": True,
            }

        target_ips = set(targets)
        self.other = [
            {
                "ip": item["ip"],
                "serial": item.get("serial") or None,
                "mac": item.get("mac"),
                "model": item.get("model"),
                "detail": item.get("error")
                or f"nalezeno {item.get('model') or 'zařízení'}, není to Force H2",
            }
            for item in self.candidates.values()
            if item["ip"] not in target_ips
        ]

        sem = asyncio.Semaphore(3)

        async def one(item: dict) -> dict:
            async with sem:
                return await asyncio.to_thread(_read_battery, item)

        results = await asyncio.gather(*(one(item) for item in targets.values()))
        for result in results:
            self._apply(result)

    def _apply(self, result: dict) -> None:
        if result.get("other"):
            self._remember_other(result)
            return
        serial = int(result.get("serial") or 0)
        row = self._match(result["ip"], serial)
        now = utcnow()
        if result.get("ok") and row and serial and int(row["logger_serial"] or 0) != serial:
            self.store.set_logger_serial(row["id"], serial)
            row = self._match(result["ip"], serial)
        if not result.get("ok"):
            if row is None:
                self._remember_other(result)
                log.info("Mimo diagnostiku %s: %s", result["ip"], result.get("error"))
                return
            self.store.insert_snapshot(_snapshot(row["id"], now, None, result.get("error")))
            last = self.store.last_success(row["id"])
            self.batteries[row["id"]] = empty_battery(row, result.get("error") or "neodpovídá", last)
            log.info("Výpadek %s: %s", result["ip"], result.get("error"))
            return

        reading = result["reading"]
        saved = self.store.upsert_battery(
            ip=result["ip"],
            logger_serial=int(result["serial"] or 0),
            mac=result.get("mac"),
            name=result.get("name"),
            manufacturer=reading.get("manufacturer"),
            model=reading.get("model"),
            firmware=reading.get("firmware"),
            bms_serial=reading.get("bms_serial"),
            module_count=reading.get("module_count"),
            cell_count=reading.get("cell_count"),
            seen=now,
        )
        self.store.insert_snapshot(_snapshot(saved["id"], now, reading, None))
        self.batteries[saved["id"]] = live_battery(saved, reading, now, now)
        log.info(
            "Force H2 %s SOC %s %%  %s V  %s A",
            result["ip"],
            reading.get("soc"),
            reading.get("voltage_v"),
            reading.get("current_a"),
        )

    def _match(self, ip: str, serial: int) -> dict | None:
        rows = [row for row in self.store.list_batteries() if row["ip"] == ip]
        if serial:
            for row in rows:
                if int(row["logger_serial"] or 0) == serial:
                    return row
        if len(rows) == 1:
            return rows[0]
        return None

    def _remember_other(self, result: dict) -> None:
        if any(item["ip"] == result["ip"] for item in self.other):
            return
        self.other.append(
            {
                "ip": result["ip"],
                "serial": result.get("serial") or None,
                "mac": result.get("mac"),
                "model": result.get("model"),
                "detail": result.get("error") or "není to Force H2",
            }
        )


def build_hub() -> Hub:
    url = os.environ.get("DATABASE_URL", "sqlite:///data/diag.db")
    path = Path(os.environ.get("CONFIG_PATH", "config.yaml"))
    devices, errors = load_config(path)
    poll = max(10, int(os.environ.get("POLL_SECONDS", "30")))
    discovery = max(60, int(os.environ.get("DISCOVERY_SECONDS", "300")))
    store = Store(url)
    store.init()
    hub = Hub(store, devices, errors, poll, discovery)
    log.info("Interval čtení %s s, prohledání sítě %s s, databáze %s", poll, discovery, url)
    return hub
