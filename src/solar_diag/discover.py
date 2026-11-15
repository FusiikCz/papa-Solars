"""Hledání Solarman loggerů výhradně v 192.168.99.0/24."""

from __future__ import annotations

import asyncio
import logging
import socket

from solar_diag.network import (
    DISCOVERY_PORT,
    SOLAR_BROADCAST,
    SOLAR_PORT,
    assert_solar_host,
    on_solar_link,
    route_source_ip,
    solar_host_ips,
)

log = logging.getLogger(__name__)

PROBE = b"WIFIKIT-214028-READ"


def parse_discovery(payload: bytes) -> dict | None:
    """Odpověď má tvar ip,mac,serial. IP mimo solární síť zahodíme."""
    if payload.strip(b"\x00") == PROBE:
        return None
    text = payload.decode("ascii", errors="ignore").strip("\x00\r\n ")
    parts = [part.strip() for part in text.split(",")]
    if len(parts) < 3 or not parts[2].isdigit():
        return None
    try:
        ip = str(assert_solar_host(parts[0]))
    except ValueError:
        return None
    return {"ip": ip, "mac": parts[1] or None, "serial": int(parts[2])}


def udp_discover(extra_ips: list[str] | None = None, timeout: float = 2.0) -> list[dict]:
    source = route_source_ip()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    found: dict[str, dict] = {}
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if source:
            try:
                sock.bind((source, 0))
            except OSError:
                sock.bind(("", 0))
        sock.settimeout(timeout)
        targets = [SOLAR_BROADCAST]
        for ip in extra_ips or []:
            try:
                targets.append(str(assert_solar_host(ip)))
            except ValueError:
                continue
        for target in targets:
            sock.sendto(PROBE, (target, DISCOVERY_PORT))
        while True:
            try:
                data, _addr = sock.recvfrom(1024)
            except socket.timeout:
                break
            item = parse_discovery(data)
            if item:
                found[item["ip"]] = item
    except OSError as exc:
        log.warning("Discovery v %s selhalo: %s", SOLAR_BROADCAST, exc)
    finally:
        sock.close()
    return list(found.values())


async def tcp_scan(timeout: float = 0.35, concurrency: int = 60) -> list[str]:
    """Kdo v solární síti poslouchá na TCP 8899."""
    sem = asyncio.Semaphore(concurrency)
    open_hosts: list[str] = []

    async def probe(ip: str) -> None:
        async with sem:
            writer = None
            try:
                _reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, SOLAR_PORT),
                    timeout,
                )
            except (OSError, asyncio.TimeoutError):
                return
            finally:
                if writer is not None:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass
            open_hosts.append(ip)

    await asyncio.gather(*(probe(ip) for ip in solar_host_ips()))
    return sorted(open_hosts, key=socket.inet_aton)


def link_status() -> dict:
    source = route_source_ip()
    return {
        "source_ip": source,
        "on_link": on_solar_link(source),
    }
