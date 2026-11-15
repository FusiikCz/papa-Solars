"""Solarman V5 a Modbus RTU. Jen čtení holding registrů (funkce 0x03)."""

from __future__ import annotations

import socket
import struct
import time
from random import randrange

from solar_diag.network import SOLAR_PORT, assert_solar_host

# Okna, která Force H2 přijme. Čtení přes jejich hranu vrací výjimku 02.
WINDOWS = (
    (0x1000, 0x108F),
    (0x1100, 0x11FF),
    (0x1400, 0x1AFF),
)


class ProtocolError(Exception):
    pass


class ModbusError(ProtocolError):
    def __init__(self, code: int):
        super().__init__(f"Modbus výjimka {code}")
        self.code = code


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def assert_read_window(address: int, quantity: int) -> None:
    if quantity < 1 or quantity > 125:
        raise ProtocolError(f"počet registrů {quantity} je mimo 1–125")
    end = address + quantity - 1
    if not any(start <= address and end <= stop for start, stop in WINDOWS):
        raise ProtocolError(f"čtení {address:#06x}+{quantity} leží mimo povolené okno")


def read_request(slave: int, address: int, quantity: int) -> bytes:
    assert_read_window(address, quantity)
    body = struct.pack(">BBHH", slave & 0xFF, 0x03, address & 0xFFFF, quantity)
    return body + struct.pack("<H", crc16(body))


def encode_request(serial: int, sequence: int, modbus_frame: bytes) -> bytes:
    """V5 požadavek ve stejném rozložení, jaké posílá pysolarmanv5."""
    payload = bytes([0x02, 0x00, 0x00]) + (b"\x00" * 12) + modbus_frame
    body = struct.pack("<H", len(payload))
    body += bytes([0x10, 0x45])
    body += struct.pack("<H", sequence & 0xFF)
    body += struct.pack("<I", serial & 0xFFFFFFFF)
    body += payload
    checksum = sum(body) & 0xFF
    return bytes([0xA5]) + body + bytes([checksum, 0x15])


def split_frames(buf: bytes) -> tuple[list[bytes], bytes]:
    frames: list[bytes] = []
    start = 0
    while True:
        begin = buf.find(b"\xA5", start)
        if begin < 0:
            return frames, b""
        if begin + 13 > len(buf):
            return frames, buf[begin:]
        payload_len = struct.unpack_from("<H", buf, begin + 1)[0]
        if payload_len > 400:
            start = begin + 1
            continue
        total = 13 + payload_len
        if begin + total > len(buf):
            return frames, buf[begin:]
        frame = buf[begin : begin + total]
        valid_end = frame[-1] == 0x15
        valid_sum = (sum(frame[1:-2]) & 0xFF) == frame[-2]
        if valid_end and valid_sum:
            frames.append(frame)
            start = begin + total
        else:
            start = begin + 1


def modbus_from_response(frame: bytes, expected_seq: int, serial: int) -> tuple[int, bytes] | None:
    """Vrátí (sériové číslo v odpovědi, modbus). Heartbeat je None."""
    if len(frame) < 13 or frame[0] != 0xA5 or frame[-1] != 0x15:
        raise ProtocolError("odpověď nemá hlavičku V5")
    if frame[4] == 0x47:
        return None
    if frame[4] != 0x15:
        raise ProtocolError(f"neočekávaný řídicí bajt {frame[4]:02x}")
    if frame[5] != (expected_seq & 0xFF):
        raise ProtocolError("nesedí číslo sekvence")
    resp_serial = struct.unpack_from("<I", frame, 7)[0]
    if serial and resp_serial != (serial & 0xFFFFFFFF):
        raise ProtocolError("odpověď patří jinému loggeru")
    if frame[11] != 0x02:
        raise ProtocolError("odpověď není z měniče nebo BMS")
    if len(frame) < 27:
        raise ProtocolError("odpověď nemá Modbus rámec")
    return resp_serial, frame[25:-2]


def parse_read_response(modbus: bytes, slave: int, quantity: int) -> list[int]:
    # Některé loggery přilepí CRC podruhé, vždy jako 0x0000.
    if len(modbus) >= 7 and modbus[-2:] == b"\x00\x00" and _crc_ok(modbus[:-2]):
        modbus = modbus[:-2]
    if not _crc_ok(modbus):
        raise ProtocolError("Modbus CRC nesedí")
    if modbus[0] != (slave & 0xFF):
        raise ProtocolError("odpověď má jiné Modbus ID")
    function = modbus[1]
    if function & 0x80:
        code = modbus[2] if len(modbus) > 2 else 0
        raise ModbusError(code)
    if function != 0x03:
        raise ProtocolError(f"přišla funkce {function}, čekám 0x03")
    count = modbus[2]
    data = modbus[3 : 3 + count]
    if len(data) != count or count != quantity * 2:
        raise ProtocolError("délka registrů nesedí")
    return [struct.unpack_from(">H", data, i)[0] for i in range(0, count, 2)]


def _crc_ok(frame: bytes) -> bool:
    if len(frame) < 4:
        return False
    body, tail = frame[:-2], frame[-2:]
    return struct.pack("<H", crc16(body)) == tail


class SolarmanClient:
    """Jedno TCP sezení na logger. Zápis do BMS tu není a nebude."""

    def __init__(self, ip: str, serial: int = 0, port: int = SOLAR_PORT, timeout: float = 4.0, slave: int = 1):
        self.ip = str(assert_solar_host(ip))
        self.serial = int(serial or 0) & 0xFFFFFFFF
        self.port = port
        self.timeout = timeout
        self.slave = slave
        self.sequence = randrange(1, 0xFF)
        self.sock: socket.socket | None = None

    def __enter__(self) -> "SolarmanClient":
        self.sock = socket.create_connection((self.ip, self.port), timeout=self.timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return self

    def __exit__(self, *_args) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def read_holding(self, address: int, quantity: int) -> list[int]:
        if self.sock is None:
            raise ProtocolError("není otevřené spojení")
        self.sequence = (self.sequence + 1) & 0xFF or 1
        seq = self.sequence
        frame = encode_request(self.serial, seq, read_request(self.slave, address, quantity))
        self.sock.sendall(frame)
        buf = b""
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self.sock.settimeout(max(0.05, deadline - time.monotonic()))
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            frames, buf = split_frames(buf)
            for candidate in frames:
                try:
                    parsed = modbus_from_response(candidate, seq, self.serial)
                except ProtocolError:
                    continue
                if parsed is None:
                    continue
                resp_serial, modbus = parsed
                if self.serial == 0 and resp_serial:
                    self.serial = resp_serial
                return parse_read_response(modbus, self.slave, quantity)
        raise TimeoutError(f"{self.ip} neodpověděl na čtení {address:#06x}")
