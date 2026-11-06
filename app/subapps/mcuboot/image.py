"""Pure-Python MCUboot signed-image parser (no crypto, stdlib only)."""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass

IMAGE_MAGIC = 0x96F3B83D
TLV_INFO_MAGIC = 0x6907
TLV_PROT_INFO_MAGIC = 0x6908
HEADER_SIZE = 32

_FLAGS = (
    (0x01, "PIC"),
    (0x04, "ENCRYPTED_AES128"),
    (0x08, "ENCRYPTED_AES256"),
    (0x10, "NON_BOOTABLE"),
    (0x20, "RAM_LOAD"),
    (0x100, "ROM_FIXED"),
)

_TLV_NAMES = {
    0x01: "KEYHASH",
    0x02: "PUBKEY",
    0x10: "SHA256",
    0x11: "SHA384",
    0x12: "SHA512",
    0x20: "RSA2048_PSS",
    0x21: "ECDSA224",
    0x22: "ECDSA_SIG",
    0x23: "RSA3072_PSS",
    0x24: "ED25519",
    0x30: "ENC_RSA2048",
    0x31: "ENC_KW",
    0x32: "ENC_EC256",
    0x33: "ENC_X25519",
    0x40: "DEPENDENCY",
    0x50: "SEC_CNT",
    0x60: "BOOT_RECORD",
}

_HASH_TLVS = {"SHA256": "sha256", "SHA384": "sha384", "SHA512": "sha512"}
_SIG_TLVS = ("RSA2048_PSS", "ECDSA224", "ECDSA_SIG", "RSA3072_PSS", "ED25519")


class McubootError(ValueError):
    """Raised when data is not a valid MCUboot image."""


@dataclass(frozen=True)
class Tlv:
    type: int
    name: str
    length: int
    value: bytes
    protected: bool


@dataclass(frozen=True)
class McubootImage:
    load_addr: int
    hdr_size: int
    protect_tlv_size: int
    img_size: int
    flags: int
    flag_names: tuple[str, ...]
    version: str
    version_tuple: tuple[int, int, int, int]
    tlvs: tuple[Tlv, ...]
    hash_type: str | None
    stored_hash: bytes | None
    computed_hash: bytes | None
    hash_ok: bool | None
    signature_types: tuple[str, ...]
    key_hash: bytes | None
    tlv_end: int
    file_size: int
    trailing_bytes: int


def tlv_name(tlv_type: int) -> str:
    return _TLV_NAMES.get(tlv_type, f"UNKNOWN_0x{tlv_type:02X}")


def _flag_names(flags: int) -> tuple[str, ...]:
    names = []
    known = 0
    for bit, name in _FLAGS:
        known |= bit
        if flags & bit:
            names.append(name)
    unknown = flags & ~known
    if unknown:
        names.append(f"UNKNOWN_0x{unknown:X}")
    return tuple(names)


def _parse_tlv_area(
    data: bytes, off: int, magic: int, protected: bool
) -> tuple[list[Tlv], int]:
    area = "protected TLV area" if protected else "TLV area"
    if off + 4 > len(data):
        raise McubootError(f"{area} header at offset {off} runs past end of file")
    got, tot = struct.unpack_from("<HH", data, off)
    if got != magic:
        raise McubootError(
            f"Bad {area} magic 0x{got:04X} at offset {off} (expected 0x{magic:04X})"
        )
    if tot < 4:
        raise McubootError(f"{area} at offset {off} has invalid size {tot}")
    end = off + tot
    if end > len(data):
        raise McubootError(
            f"{area} (offset {off}, size {tot}) runs past end of file ({len(data)} bytes)"
        )
    tlvs: list[Tlv] = []
    pos = off + 4
    while pos < end:
        if pos + 4 > end:
            raise McubootError(f"TLV entry header at offset {pos} overruns {area}")
        t, ln = struct.unpack_from("<HH", data, pos)
        pos += 4
        if pos + ln > end:
            raise McubootError(
                f"TLV entry 0x{t:02X} at offset {pos - 4} (length {ln}) overruns {area}"
            )
        tlvs.append(Tlv(t, tlv_name(t), ln, bytes(data[pos : pos + ln]), protected))
        pos += ln
    return tlvs, end


def parse_image(data: bytes) -> McubootImage:
    data = bytes(data)
    n = len(data)
    if n < HEADER_SIZE:
        raise McubootError(
            f"File too small for an MCUboot header ({n} bytes, need {HEADER_SIZE})"
        )
    (magic, load_addr, hdr_size, prot_size, img_size, flags,
     major, minor, rev, build, _pad) = struct.unpack_from("<IIHHIIBBHII", data, 0)
    if magic != IMAGE_MAGIC:
        raise McubootError(
            f"Bad image magic 0x{magic:08X} (expected 0x{IMAGE_MAGIC:08X})"
        )
    body_end = hdr_size + img_size
    if hdr_size < HEADER_SIZE:
        raise McubootError(f"Header size {hdr_size} is smaller than {HEADER_SIZE}")
    if body_end > n:
        raise McubootError(
            f"Image header/body ({body_end} bytes) runs past end of file ({n} bytes)"
        )

    tlvs: list[Tlv] = []
    off = body_end
    if prot_size > 0:
        ptlvs, pend = _parse_tlv_area(data, off, TLV_PROT_INFO_MAGIC, True)
        if pend - off != prot_size:
            raise McubootError(
                f"Protected TLV area size {pend - off} does not match header "
                f"protect_tlv_size {prot_size}"
            )
        tlvs.extend(ptlvs)
        off = pend
    utlvs, tlv_end = _parse_tlv_area(data, off, TLV_INFO_MAGIC, False)
    tlvs.extend(utlvs)

    hash_type = stored = computed = None
    hash_ok = None
    for t in tlvs:
        if t.name in _HASH_TLVS and not t.protected:
            hash_type, stored = t.name, t.value
            break
    if hash_type is not None:
        computed = hashlib.new(_HASH_TLVS[hash_type], data[: body_end + prot_size]).digest()
        hash_ok = computed == stored

    sigs = tuple(t.name for t in tlvs if t.name in _SIG_TLVS)
    key_hash = next((t.value for t in tlvs if t.name == "KEYHASH"), None)

    return McubootImage(
        load_addr=load_addr,
        hdr_size=hdr_size,
        protect_tlv_size=prot_size,
        img_size=img_size,
        flags=flags,
        flag_names=_flag_names(flags),
        version=f"{major}.{minor}.{rev}+{build}",
        version_tuple=(major, minor, rev, build),
        tlvs=tuple(tlvs),
        hash_type=hash_type,
        stored_hash=stored,
        computed_hash=computed,
        hash_ok=hash_ok,
        signature_types=sigs,
        key_hash=key_hash,
        tlv_end=tlv_end,
        file_size=n,
        trailing_bytes=n - tlv_end,
    )


def parse_file(path: str | os.PathLike) -> McubootImage:
    with open(path, "rb") as f:
        return parse_image(f.read())


def looks_like_mcuboot(data_or_path) -> bool:
    """Cheap magic check on bytes or a file path; never raises."""
    try:
        if isinstance(data_or_path, (bytes, bytearray, memoryview)):
            head = bytes(data_or_path[:4])
        else:
            with open(data_or_path, "rb") as f:
                head = f.read(4)
        return len(head) == 4 and struct.unpack("<I", head)[0] == IMAGE_MAGIC
    except Exception:
        return False
