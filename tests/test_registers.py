from solar_diag.registers import decode


def write_ascii(regs: dict, start: int, count: int, text: str) -> None:
    raw = text.encode("ascii")[: count * 2].ljust(count * 2, b"\x00")
    for index in range(count):
        regs[start + index] = (raw[index * 2] << 8) | raw[index * 2 + 1]


def force_regs(**extra) -> dict:
    regs = {
        0x1400: 1 << 11,
        0x1401: 0,
        0x1402: 0,
        0x1403: 4096,
        0x1404: 0,
        0x1405: 1234,
        0x1406: 280,
        0x1407: 80,
        0x1408: 12,
        0x140F: 0x0003,
        0x1410: 3340,
        0x1411: 3320,
        0x1420: 97,
        0x1436: 1,
        0x1437: 2,
        0x1460: 10240,
        0x14B0: 275,
        0x1500: 3340,
        0x1501: 3320,
    }
    write_ascii(regs, 0x1000, 5, "Pylon")
    write_ascii(regs, 0x1005, 5, "Force_H2")
    regs[0x100A] = 0x0200
    regs[0x100B] = (52 << 8) | 34
    regs.update(extra)
    return regs


def test_decodes_force_h2_without_inventing_alarms():
    reading = decode(force_regs())
    assert reading["decoded"] is True
    assert reading["is_force_h2"] is True
    assert reading["model"] == "Force_H2"
    assert reading["firmware"] == "V2.0 B52.34"
    assert reading["mode"] == "charge"
    assert reading["soc"] == 80
    assert reading["voltage_v"] == 409.6
    assert reading["current_a"] == 12.34
    assert reading["cell_delta_mv"] == 20
    assert reading["modules"] == [{"index": 0, "voltage_v": 102.4, "temp_c": 27.5}]
    assert reading["cells"][1]["module"] == 0
    assert reading["cells"][1]["cell"] == 1
    assert reading["alarms"] == []
    assert reading["quality_ok"] is True


def test_bms_bit_is_the_alarm_not_a_homemade_threshold():
    reading = decode(force_regs(**{0x1402: 1 << 14}))
    assert reading["alarms"] == [{"level": "alarm", "text": "Výstraha: vysoké napětí článku"}]


def test_implausible_soc_is_kept_and_marked():
    reading = decode(force_regs(**{0x1407: 250}))
    assert reading["soc"] == 250
    assert reading["quality_ok"] is False
    assert any("SOC" in note for note in reading["quality_notes"])


def test_force_h1_is_not_accepted_as_h2():
    regs = force_regs()
    write_ascii(regs, 0x1005, 5, "Force_H1")
    assert decode(regs)["is_force_h2"] is False
