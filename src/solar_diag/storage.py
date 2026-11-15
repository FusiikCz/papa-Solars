"""Historie měření. Výchozí je SQLite, PostgreSQL bere DATABASE_URL."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

SNAPSHOT_COLUMNS = (
    "battery_id",
    "ts",
    "online",
    "error",
    "soc",
    "soh",
    "voltage_v",
    "current_a",
    "power_w",
    "bms_temp_c",
    "cycle_count",
    "cell_delta_mv",
    "min_cell_mv",
    "max_cell_mv",
    "remaining_wh",
    "charged_today_wh",
    "discharged_today_wh",
    "mode",
    "has_alarm",
    "quality_ok",
    "modules",
    "cells",
    "alarms",
    "notices",
    "quality_notes",
)
JSON_COLUMNS = {"modules", "cells", "alarms", "notices", "quality_notes"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def dump_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def load_ts(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(microsecond=0)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "T" in text:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0)
    return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def iso(value) -> str | None:
    parsed = load_ts(value)
    if parsed is None:
        return None
    return parsed.isoformat()


class Store:
    def __init__(self, url: str):
        self.url = url
        self.kind = "sqlite" if url.startswith("sqlite:") else "postgres"
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._pg = None
        if self.kind == "sqlite":
            path = Path(url.removeprefix("sqlite:///"))
            if not path.is_absolute():
                path = Path.cwd() / path
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
        if self._pg is not None:
            self._pg.close()

    def init(self) -> None:
        if self.kind == "postgres":
            self._connect_postgres()
        statements = _schema(self.kind)
        for statement in statements:
            self._run(statement)

    def _connect_postgres(self) -> None:
        import time

        import psycopg
        from psycopg.rows import dict_row

        last_error = None
        for _attempt in range(30):
            try:
                self._pg = psycopg.connect(self.url, autocommit=True, row_factory=dict_row)
                self._pg.execute("SET TIME ZONE 'UTC'")
                return
            except Exception as exc:
                last_error = exc
                time.sleep(1)
        raise RuntimeError(f"PostgreSQL není dostupný: {last_error}")

    def _q(self, sql: str) -> str:
        if self.kind == "sqlite":
            return sql.replace("%s", "?")
        return sql

    def _run(self, sql: str, params: tuple = ()) -> None:
        sql = self._q(sql)
        with self._lock:
            if self.kind == "sqlite":
                self._conn.execute(sql, params)
                self._conn.commit()
                return
            self._pg.execute(sql, params)

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        sql = self._q(sql)
        with self._lock:
            if self.kind == "sqlite":
                rows = self._conn.execute(sql, params).fetchall()
                return [dict(row) for row in rows]
            return [dict(row) for row in self._pg.execute(sql, params).fetchall()]

    def _one(self, sql: str, params: tuple = ()) -> dict | None:
        rows = self._all(sql, params)
        return rows[0] if rows else None

    def _json(self, value):
        if self.kind == "sqlite":
            return json.dumps(value if value is not None else [], ensure_ascii=False)
        from psycopg.types.json import Json

        return Json(value if value is not None else [])

    def _load_json(self, value):
        if value is None or isinstance(value, (list, dict)):
            return value
        return json.loads(value)

    def upsert_battery(
        self,
        *,
        ip: str,
        logger_serial: int,
        mac: str | None,
        name: str | None,
        manufacturer: str | None,
        model: str | None,
        firmware: str | None,
        bms_serial: str | None,
        module_count: int | None,
        cell_count: int | None,
        seen: datetime | None,
    ) -> dict:
        current = self._one(
            "SELECT * FROM batteries WHERE ip = %s AND logger_serial = %s",
            (ip, logger_serial),
        )
        if current is None:
            self._run(
                """
                INSERT INTO batteries (
                    ip, logger_serial, mac, name, manufacturer, model, firmware,
                    bms_serial, module_count, cell_count, first_seen, last_seen
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    ip,
                    logger_serial,
                    mac,
                    name or f"Force H2 {ip}",
                    manufacturer,
                    model,
                    firmware,
                    bms_serial,
                    module_count,
                    cell_count,
                    dump_ts(seen or utcnow()),
                    dump_ts(seen) if seen else None,
                ),
            )
        else:
            self._run(
                """
                UPDATE batteries SET
                    mac = COALESCE(%s, mac),
                    name = COALESCE(%s, name),
                    manufacturer = COALESCE(%s, manufacturer),
                    model = COALESCE(%s, model),
                    firmware = COALESCE(%s, firmware),
                    bms_serial = COALESCE(%s, bms_serial),
                    module_count = COALESCE(%s, module_count),
                    cell_count = COALESCE(%s, cell_count),
                    last_seen = COALESCE(%s, last_seen)
                WHERE id = %s
                """,
                (
                    mac,
                    name,
                    manufacturer,
                    model,
                    firmware,
                    bms_serial,
                    module_count,
                    cell_count,
                    dump_ts(seen) if seen else None,
                    current["id"],
                ),
            )
        row = self._one(
            "SELECT * FROM batteries WHERE ip = %s AND logger_serial = %s",
            (ip, logger_serial),
        )
        return _battery_row(row)

    def set_logger_serial(self, battery_id: int, serial: int) -> None:
        self._run(
            "UPDATE batteries SET logger_serial = %s WHERE id = %s",
            (serial, battery_id),
        )

    def list_batteries(self) -> list[dict]:
        rows = self._all("SELECT * FROM batteries ORDER BY ip, logger_serial")
        return [_battery_row(row) for row in rows]

    def last_success(self, battery_id: int) -> datetime | None:
        row = self._one(
            "SELECT MAX(ts) AS ts FROM snapshots WHERE battery_id = %s AND online = %s",
            (battery_id, True),
        )
        if not row:
            return None
        return load_ts(row["ts"])

    def insert_snapshot(self, row: dict) -> None:
        values = []
        for column in SNAPSHOT_COLUMNS:
            value = row.get(column)
            if column in JSON_COLUMNS:
                value = self._json(value)
            elif column in {"online", "has_alarm", "quality_ok"}:
                value = bool(value) if value is not None else False
                if self.kind == "sqlite":
                    value = int(value)
            elif column == "ts":
                value = dump_ts(value if isinstance(value, datetime) else utcnow())
            values.append(value)
        placeholders = ", ".join(["%s"] * len(SNAPSHOT_COLUMNS))
        columns = ", ".join(SNAPSHOT_COLUMNS)
        self._run(
            f"INSERT INTO snapshots ({columns}) VALUES ({placeholders})",
            tuple(values),
        )

    def history(self, battery_id: int, since: datetime) -> list[dict]:
        rows = self._all(
            """
            SELECT ts, soc, soh, voltage_v, current_a, power_w, bms_temp_c,
                   min_cell_mv, max_cell_mv, cell_delta_mv
            FROM snapshots
            WHERE battery_id = %s AND ts >= %s AND online = %s
            ORDER BY ts
            """,
            (battery_id, dump_ts(since), True),
        )
        points = []
        for row in rows:
            points.append(
                {
                    "t": iso(row["ts"]),
                    "soc": row["soc"],
                    "soh": row["soh"],
                    "voltage_v": row["voltage_v"],
                    "current_a": row["current_a"],
                    "power_w": row["power_w"],
                    "bms_temp_c": row["bms_temp_c"],
                    "min_cell_mv": row["min_cell_mv"],
                    "max_cell_mv": row["max_cell_mv"],
                    "cell_delta_mv": row["cell_delta_mv"],
                }
            )
        return _stride(points, 800)

    def cell_history(self, battery_id: int, cell_index: int, since: datetime) -> list[dict]:
        rows = self._all(
            """
            SELECT ts, cells
            FROM snapshots
            WHERE battery_id = %s AND ts >= %s AND online = %s
            ORDER BY ts
            """,
            (battery_id, dump_ts(since), True),
        )
        points = []
        for row in rows:
            cells = self._load_json(row["cells"]) or []
            millivolts = None
            if isinstance(cells, list):
                for item in cells:
                    if isinstance(item, dict) and item.get("index") == cell_index:
                        millivolts = item.get("mv")
                        break
            if millivolts is None:
                continue
            points.append({"t": iso(row["ts"]), "mv": millivolts})
        return _stride(points, 800)

    def events(self, battery_id: int, since: datetime) -> list[dict]:
        rows = self._all(
            """
            SELECT ts, online, error, alarms, notices
            FROM snapshots
            WHERE battery_id = %s AND ts >= %s AND (online = %s OR has_alarm = %s)
            ORDER BY ts DESC
            LIMIT 300
            """,
            (battery_id, dump_ts(since), False, True),
        )
        return [
            {
                "t": iso(row["ts"]),
                "online": bool(row["online"]),
                "error": row["error"],
                "alarms": self._load_json(row["alarms"]) or [],
                "notices": self._load_json(row["notices"]) or [],
            }
            for row in rows
        ]


def _battery_row(row: dict | None) -> dict:
    if row is None:
        raise RuntimeError("baterie se neuložila")
    return {
        "id": row["id"],
        "ip": row["ip"],
        "logger_serial": row["logger_serial"],
        "mac": row["mac"],
        "name": row["name"],
        "manufacturer": row["manufacturer"],
        "model": row["model"],
        "firmware": row["firmware"],
        "bms_serial": row["bms_serial"],
        "module_count": row["module_count"],
        "cell_count": row["cell_count"],
        "first_seen": iso(row["first_seen"]),
        "last_seen": iso(row["last_seen"]),
    }


def _schema(kind: str) -> list[str]:
    if kind == "sqlite":
        id_type = "INTEGER PRIMARY KEY AUTOINCREMENT"
        bool_type = "INTEGER NOT NULL"
        json_type = "TEXT"
    else:
        id_type = "BIGSERIAL PRIMARY KEY"
        bool_type = "BOOLEAN NOT NULL"
        json_type = "JSONB"
    return [
        f"""
        CREATE TABLE IF NOT EXISTS batteries (
            id {id_type},
            ip TEXT NOT NULL,
            logger_serial BIGINT NOT NULL,
            mac TEXT,
            name TEXT NOT NULL,
            manufacturer TEXT,
            model TEXT,
            firmware TEXT,
            bms_serial TEXT,
            module_count INTEGER,
            cell_count INTEGER,
            first_seen TEXT NOT NULL,
            last_seen TEXT,
            UNIQUE (ip, logger_serial)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS snapshots (
            id {id_type},
            battery_id BIGINT NOT NULL REFERENCES batteries(id),
            ts TEXT NOT NULL,
            online {bool_type},
            error TEXT,
            soc INTEGER,
            soh INTEGER,
            voltage_v DOUBLE PRECISION,
            current_a DOUBLE PRECISION,
            power_w DOUBLE PRECISION,
            bms_temp_c DOUBLE PRECISION,
            cycle_count INTEGER,
            cell_delta_mv INTEGER,
            min_cell_mv INTEGER,
            max_cell_mv INTEGER,
            remaining_wh BIGINT,
            charged_today_wh BIGINT,
            discharged_today_wh BIGINT,
            mode TEXT,
            has_alarm {bool_type},
            quality_ok {bool_type},
            modules {json_type},
            cells {json_type},
            alarms {json_type},
            notices {json_type},
            quality_notes {json_type}
        )
        """,
        "CREATE INDEX IF NOT EXISTS snapshots_battery_ts ON snapshots (battery_id, ts)",
    ]


def _stride(points: list[dict], limit: int) -> list[dict]:
    if len(points) <= limit:
        return points
    step = len(points) / limit
    picked = [points[min(len(points) - 1, int(i * step))] for i in range(limit)]
    if picked[-1] is not points[-1]:
        picked[-1] = points[-1]
    return picked


def since_hours(hours: int) -> datetime:
    bounded = min(max(int(hours), 1), 168)
    return utcnow() - timedelta(hours=bounded)
