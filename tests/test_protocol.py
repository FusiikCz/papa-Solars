import struct

import pytest

from solar_diag.protocol import (
    ProtocolError,
    crc16,
    encode_request,
    modbus_from_response,
    parse_read_response,
    read_request,
    split_frames,
)


def test_modbus_crc_known_vector():
    assert struct.pack("<H", crc16(bytes.fromhex("01030000000A"))) == bytes.fromhex("C5CD")


def test_read_stays_inside_force_h2_windows():
    frame = read_request(1, 0x1400, 58)
    assert frame[1] == 0x03
    with pytest.raises(ProtocolError):
        read_request(1, 0x1080, 40)
    with pytest.raises(ProtocolError):
        read_request(1, 0x2000, 1)


def test_v5_request_layout():
    modbus = read_request(1, 0x1407, 1)
    frame = encode_request(3912345678, 0x22, modbus)
    assert frame[0] == 0xA5
    assert frame[-1] == 0x15
    assert frame[3:5] == bytes([0x10, 0x45])
    assert frame[5] == 0x22
    assert int.from_bytes(frame[7:11], "little") == 3912345678
    payload_len = int.from_bytes(frame[1:3], "little")
    assert len(frame) == 13 + payload_len
    assert (sum(frame[1:-2]) & 0xFF) == frame[-2]


def _response(serial: int, seq: int, modbus: bytes) -> bytes:
    payload = bytes([0x02, 0x01]) + struct.pack("<III", 10, 20, 30) + modbus
    body = struct.pack("<H", len(payload))
    body += bytes([0x10, 0x15, seq & 0xFF, 0x00])
    body += struct.pack("<I", serial)
    body += payload
    return bytes([0xA5]) + body + bytes([sum(body) & 0xFF, 0x15])


def test_response_roundtrip_and_double_crc():
    body = bytes.fromhex("0103020037")
    modbus = body + struct.pack("<H", crc16(body))
    frame = _response(99, 7, modbus)
    frames, rest = split_frames(frame + b"\x00\x01")
    assert rest == b""
    assert len(frames) == 1
    resp_serial, got = modbus_from_response(frames[0], 7, 99)
    assert resp_serial == 99
    assert parse_read_response(got, 1, 1) == [0x37]
    assert parse_read_response(got + b"\x00\x00", 1, 1) == [0x37]

    broken = bytearray(frame)
    broken[-2] ^= 0xFF
    assert split_frames(bytes(broken))[0] == []
