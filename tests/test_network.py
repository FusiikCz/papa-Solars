from pathlib import Path

import pytest

from solar_diag.config import load_config
from solar_diag.discover import parse_discovery
from solar_diag.network import (
    SOLAR_SUBNET,
    OutsideSolarNetwork,
    assert_solar_host,
    solar_host_ips,
)
from solar_diag.protocol import SolarmanClient


def test_subnet_is_the_solar_lan():
    assert SOLAR_SUBNET == "192.168.99.0/24"
    hosts = solar_host_ips()
    assert len(hosts) == 254
    assert hosts[0] == "192.168.99.1"
    assert hosts[-1] == "192.168.99.254"
    assert all(item.startswith("192.168.99.") for item in hosts)


def test_rejects_other_networks_and_broadcast():
    with pytest.raises(OutsideSolarNetwork):
        assert_solar_host("192.168.1.20")
    with pytest.raises(OutsideSolarNetwork):
        assert_solar_host("192.168.99.255")
    with pytest.raises(OutsideSolarNetwork):
        assert_solar_host("192.168.99.0")
    assert str(assert_solar_host("192.168.99.40")) == "192.168.99.40"


def test_client_refuses_foreign_ip_before_connecting():
    with pytest.raises(OutsideSolarNetwork):
        SolarmanClient("8.8.8.8", 1)


def test_discovery_drops_replies_outside_the_solar_lan():
    assert parse_discovery(b"10.0.0.5,AABBCCDDEEFF,123456") is None
    assert parse_discovery(b"192.168.88.9,AABBCCDDEEFF,123456") is None
    found = parse_discovery(b"192.168.99.20,AABBCCDDEEFF,3912345678")
    assert found == {"ip": "192.168.99.20", "mac": "AABBCCDDEEFF", "serial": 3912345678}


def test_config_cannot_retarget_the_subnet(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "subnet: 10.0.0.0/8\n"
        "devices:\n"
        "  - ip: 10.0.0.5\n"
        "    serial: 1\n"
        "  - ip: 192.168.99.40\n"
        "    serial: 99\n"
        "    name: Dum\n",
        encoding="utf-8",
    )
    devices, errors = load_config(path)
    assert devices == [{"ip": "192.168.99.40", "serial": 99, "name": "Dum"}]
    assert any("192.168.99.0/24" in error for error in errors)
    assert any("10.0.0.5" in error for error in errors)
