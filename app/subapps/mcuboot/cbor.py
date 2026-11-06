"""Minimal CBOR (RFC 8949) codec covering what SMP/mcumgr needs.

Encodes: ints (up to 64-bit), bytes, str, list/tuple, dict, bool, None, float.
Decodes the same plus half/single/double floats, tags (ignored, inner value is
returned), ``undefined`` (as None) and indefinite-length strings/arrays/maps.
"""
from __future__ import annotations

import struct
from typing import Any

__all__ = ["CborError", "dumps", "loads"]

_MAX_DEPTH = 64


class CborError(ValueError):
    """Malformed or unsupported CBOR."""


class _Break:
    pass


_BREAK = _Break()


def _head(major: int, value: int) -> bytes:
    m = major << 5
    if value < 24:
        return bytes([m | value])
    if value < 0x100:
        return bytes([m | 24, value])
    if value < 0x10000:
        return bytes([m | 25]) + struct.pack(">H", value)
    if value < 0x100000000:
        return bytes([m | 26]) + struct.pack(">I", value)
    if value < 0x10000000000000000:
        return bytes([m | 27]) + struct.pack(">Q", value)
    raise CborError("integer too large")


def dumps(obj: Any) -> bytes:
    out = bytearray()
    _enc(obj, out, 0)
    return bytes(out)


def _enc(obj: Any, out: bytearray, depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise CborError("nesting too deep")
    if obj is None:
        out.append(0xF6)
    elif obj is True:
        out.append(0xF5)
    elif obj is False:
        out.append(0xF4)
    elif isinstance(obj, int):
        if obj >= 0:
            out += _head(0, obj)
        else:
            out += _head(1, -1 - obj)
    elif isinstance(obj, (bytes, bytearray, memoryview)):
        b = bytes(obj)
        out += _head(2, len(b)) + b
    elif isinstance(obj, str):
        b = obj.encode("utf-8")
        out += _head(3, len(b)) + b
    elif isinstance(obj, (list, tuple)):
        out += _head(4, len(obj))
        for v in obj:
            _enc(v, out, depth + 1)
    elif isinstance(obj, dict):
        out += _head(5, len(obj))
        for k, v in obj.items():
            _enc(k, out, depth + 1)
            _enc(v, out, depth + 1)
    elif isinstance(obj, float):
        out.append(0xFB)
        out += struct.pack(">d", obj)
    else:
        raise CborError(f"cannot encode {type(obj).__name__}")


def loads(data: bytes) -> Any:
    data = bytes(data)
    value, pos = _dec(data, 0, 0)
    if value is _BREAK:
        raise CborError("unexpected break")
    if pos != len(data):
        raise CborError("trailing bytes after CBOR item")
    return value


def _take(data: bytes, pos: int, n: int) -> tuple[bytes, int]:
    if n < 0 or pos + n > len(data):
        raise CborError("truncated input")
    return data[pos:pos + n], pos + n


def _arg(data: bytes, pos: int, info: int) -> tuple[int | None, int]:
    """Decode the argument; returns (None, pos) for indefinite (info 31)."""
    if info < 24:
        return info, pos
    if info == 24:
        b, pos = _take(data, pos, 1)
        return b[0], pos
    if info == 25:
        b, pos = _take(data, pos, 2)
        return struct.unpack(">H", b)[0], pos
    if info == 26:
        b, pos = _take(data, pos, 4)
        return struct.unpack(">I", b)[0], pos
    if info == 27:
        b, pos = _take(data, pos, 8)
        return struct.unpack(">Q", b)[0], pos
    if info == 31:
        return None, pos
    raise CborError(f"reserved additional info {info}")


def _dec(data: bytes, pos: int, depth: int) -> tuple[Any, int]:
    if depth > _MAX_DEPTH:
        raise CborError("nesting too deep")
    if pos >= len(data):
        raise CborError("truncated input")
    ib = data[pos]
    pos += 1
    major, info = ib >> 5, ib & 0x1F

    if major == 7:
        if info == 20:
            return False, pos
        if info == 21:
            return True, pos
        if info in (22, 23):
            return None, pos
        if info == 25:
            b, pos = _take(data, pos, 2)
            return struct.unpack(">e", b)[0], pos
        if info == 26:
            b, pos = _take(data, pos, 4)
            return struct.unpack(">f", b)[0], pos
        if info == 27:
            b, pos = _take(data, pos, 8)
            return struct.unpack(">d", b)[0], pos
        if info == 31:
            return _BREAK, pos
        raise CborError(f"unsupported simple value {info}")

    n, pos = _arg(data, pos, info)

    if major in (0, 1):
        if n is None:
            raise CborError("indefinite length not allowed for integers")
        return (n if major == 0 else -1 - n), pos
    if major == 6:
        if n is None:
            raise CborError("indefinite length not allowed for tags")
        item, pos = _dec(data, pos, depth + 1)
        if item is _BREAK:
            raise CborError("unexpected break")
        return item, pos
    if major in (2, 3):
        if n is None:
            parts = bytearray()
            while True:
                if pos >= len(data):
                    raise CborError("truncated input")
                if data[pos] == 0xFF:
                    pos += 1
                    break
                ch = data[pos]
                if ch >> 5 != major or ch & 0x1F == 31:
                    raise CborError("bad chunk in indefinite string")
                pos += 1
                cn, pos = _arg(data, pos, ch & 0x1F)
                chunk, pos = _take(data, pos, cn or 0)
                parts += chunk
            raw = bytes(parts)
        else:
            raw, pos = _take(data, pos, n)
        if major == 2:
            return raw, pos
        try:
            return raw.decode("utf-8"), pos
        except UnicodeDecodeError as e:
            raise CborError("invalid UTF-8 in text string") from e
    if major == 4:
        items: list[Any] = []
        if n is None:
            while True:
                item, pos = _dec(data, pos, depth + 1)
                if item is _BREAK:
                    break
                items.append(item)
        else:
            if n > len(data) - pos:
                raise CborError("truncated input")
            for _ in range(n):
                item, pos = _dec(data, pos, depth + 1)
                if item is _BREAK:
                    raise CborError("unexpected break")
                items.append(item)
        return items, pos
    # major == 5
    result: dict[Any, Any] = {}
    if n is not None and 2 * n > len(data) - pos:
        raise CborError("truncated input")
    count = 0
    while n is None or count < n:
        k, pos = _dec(data, pos, depth + 1)
        if k is _BREAK:
            if n is None:
                break
            raise CborError("unexpected break")
        v, pos = _dec(data, pos, depth + 1)
        if v is _BREAK:
            raise CborError("break inside map entry")
        if isinstance(k, (list, dict)):
            raise CborError("unsupported map key type")
        result[k] = v
        count += 1
    return result, pos
