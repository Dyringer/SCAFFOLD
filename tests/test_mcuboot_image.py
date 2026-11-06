import hashlib
import struct

import pytest

from app.subapps.mcuboot.image import McubootError, looks_like_mcuboot, parse_file, parse_image


def tlv_area(magic, entries):
    body = b"".join(struct.pack("<HH", t, len(v)) + v for t, v in entries)
    return struct.pack("<HH", magic, 4 + len(body)) + body


def build(
    body=b"\xaa" * 100,
    protected=(),
    hash_tlv=True,
    flags=0x01,
    hdr_size=0x200,
    trailing=b"",
    extra=(),
):
    prot = tlv_area(0x6908, protected) if protected else b""
    header = struct.pack(
        "<IIHHIIBBHII", 0x96F3B83D, 0x1000, hdr_size, len(prot), len(body),
        flags, 1, 2, 3, 4, 0,
    )
    header += b"\x00" * (hdr_size - len(header))
    signed = header + body + prot
    entries = []
    if hash_tlv:
        entries.append((0x10, hashlib.sha256(signed).digest()))
    entries += [(0x01, b"\x11" * 32), (0x22, b"\x22" * 72)]
    entries += list(extra)
    return signed + tlv_area(0x6907, entries) + trailing


def test_valid():
    img = parse_image(build())
    assert img.load_addr == 0x1000
    assert img.hdr_size == 0x200
    assert img.img_size == 100
    assert img.flag_names == ("PIC",)
    assert img.version == "1.2.3+4"
    assert img.version_tuple == (1, 2, 3, 4)
    assert img.hash_type == "SHA256"
    assert img.hash_ok is True
    assert img.stored_hash == img.computed_hash
    assert img.signature_types == ("ECDSA_SIG",)
    assert img.key_hash == b"\x11" * 32
    assert [t.name for t in img.tlvs] == ["SHA256", "KEYHASH", "ECDSA_SIG"]
    assert img.trailing_bytes == 0
    assert img.tlv_end == img.file_size


def test_protected_tlvs():
    data = build(protected=[(0x50, b"\x01\x00\x00\x00")])
    img = parse_image(data)
    assert img.protect_tlv_size == 12
    assert img.hash_ok is True
    assert img.tlvs[0].protected and img.tlvs[0].name == "SEC_CNT"
    assert not img.tlvs[1].protected
    # hash must cover the protected area: tampering with it breaks the hash
    off = 0x200 + 100 + 8
    bad = bytearray(data)
    bad[off] ^= 0xFF
    assert parse_image(bytes(bad)).hash_ok is False


def test_corrupt_body():
    data = bytearray(build())
    data[0x200 + 5] ^= 0xFF
    assert parse_image(bytes(data)).hash_ok is False


def test_no_hash():
    img = parse_image(build(hash_tlv=False))
    assert img.hash_ok is None
    assert img.hash_type is None and img.computed_hash is None


def test_bad_magic():
    data = bytearray(build())
    data[0:4] = b"\x00\x00\x00\x00"
    with pytest.raises(McubootError, match="0x00000000"):
        parse_image(bytes(data))


def test_truncated():
    with pytest.raises(McubootError):
        parse_image(b"\x3d\xb8\xf3\x96")
    with pytest.raises(McubootError):
        parse_image(build()[:0x200 + 50])
    with pytest.raises(McubootError):
        parse_image(build()[:-10])


def test_bad_tlv_magic():
    data = bytearray(build())
    data[0x200 + 100] = 0x00
    with pytest.raises(McubootError, match="magic"):
        parse_image(bytes(data))


def test_overrunning_tlv():
    data = bytearray(build(hash_tlv=False))
    # first entry (KEYHASH) length field -> huge
    pos = 0x200 + 100 + 4 + 2
    struct.pack_into("<H", data, pos, 500)
    with pytest.raises(McubootError, match="overruns"):
        parse_image(bytes(data))


def test_trailing_bytes():
    img = parse_image(build(trailing=b"\xff" * 33))
    assert img.trailing_bytes == 33
    assert img.hash_ok is True


def test_unknown_flags_and_tlv():
    img = parse_image(build(flags=0x01 | 0x10 | 0x1000, extra=[(0x7F, b"ab")]))
    assert img.flag_names == ("PIC", "NON_BOOTABLE", "UNKNOWN_0x1000")
    assert img.tlvs[-1].name == "UNKNOWN_0x7F"
    assert img.tlvs[-1].value == b"ab"


def test_file_and_looks_like(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(build())
    assert parse_file(p).hash_ok is True
    assert looks_like_mcuboot(p)
    assert looks_like_mcuboot(str(p))
    assert looks_like_mcuboot(build())
    assert not looks_like_mcuboot(b"nope")
    assert not looks_like_mcuboot(tmp_path / "missing.bin")
    assert not looks_like_mcuboot(None)
