"""Jediná síť, do které diagnostika smí sáhnout."""

from __future__ import annotations

import ipaddress
import socket

SOLAR_SUBNET = "192.168.99.0/24"
SOLAR_NETWORK = ipaddress.ip_network(SOLAR_SUBNET)
SOLAR_BROADCAST = str(SOLAR_NETWORK.broadcast_address)
SOLAR_PORT = 8899
DISCOVERY_PORT = 48899


class OutsideSolarNetwork(ValueError):
    """Cíl není hostitel v síti solárů."""


def assert_solar_host(ip: str) -> ipaddress.IPv4Address:
    """Pustí dál jen jednu adresu z 192.168.99.1 až 192.168.99.254."""
    try:
        addr = ipaddress.ip_address(str(ip).strip())
    except ValueError as exc:
        raise OutsideSolarNetwork(f"{ip} není IP adresa solární sítě") from exc
    if not isinstance(addr, ipaddress.IPv4Address) or addr not in SOLAR_NETWORK:
        raise OutsideSolarNetwork(
            f"{ip} je mimo {SOLAR_SUBNET}. Diagnostika jinam nechodí."
        )
    if addr in (SOLAR_NETWORK.network_address, SOLAR_NETWORK.broadcast_address):
        raise OutsideSolarNetwork(f"{ip} není adresa zařízení")
    return addr


def solar_host_ips() -> list[str]:
    return [str(addr) for addr in SOLAR_NETWORK.hosts()]


def route_source_ip() -> str | None:
    """Adresa, kterou systém použije jako zdroj cesty do solární sítě.

    UDP connect nic neodesílá, jen se zeptá směrovací tabulky.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((str(next(SOLAR_NETWORK.hosts())), 9))
        ip = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    if ip.startswith("127."):
        return None
    return ip


def on_solar_link(source_ip: str | None = None) -> bool:
    ip = route_source_ip() if source_ip is None else source_ip
    if not ip:
        return False
    try:
        return ipaddress.ip_address(ip) in SOLAR_NETWORK
    except ValueError:
        return False
