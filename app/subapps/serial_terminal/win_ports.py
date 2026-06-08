"""Windows-only: read each COM port's *Bus reported device description*.

`QSerialPortInfo` exposes the USB product description (e.g. "PICO_CORE") but
NOT the per-interface name a composite device reports on the bus — the field
Windows shows as "Bus reported device description" and pyserial exposes as
`port.interface`. For a device with two CDC interfaces both reading
"PICO_CORE", that bus name (e.g. "Console" / "DCP") is the only thing that
tells them apart.

It is not a plain registry value; it lives in the device property
`DEVPKEY_Device_BusReportedDeviceDesc`, read here via SetupAPI through ctypes
(the same Configuration-Manager path pyserial uses) so we need no extra
dependency. On any non-Windows platform, or if the lookup fails for any
reason, `bus_reported_names()` returns an empty dict and callers fall back to
the plain description.
"""
# ruff: noqa: N801, N806 -- Win32 API type/function names are kept verbatim
# (DWORD, SP_DEVINFO_DATA, SetupDiGetClassDevs, …) so they match the documented
# Windows API rather than PEP-8 casing.
from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

# GUID for the Ports (COM & LPT) device class.
_GUID_DEVCLASS_PORTS = "{4D36E978-E325-11CE-BFC1-08002BE10318}"
_DIGCF_PRESENT = 0x02

# DEVPKEY_Device_BusReportedDeviceDesc = {540b947e-...}, pid 4
_PK_BUS_DESC = ("{540B947E-8B40-45BC-A8A2-6A0B894CBDA2}", 4)
# DEVPKEY_Device_FriendlyName = {a45c254e-...}, pid 14
_PK_FRIENDLY = ("{A45C254E-DF1C-4EFD-8020-67D146A850E0}", 14)


def bus_reported_names() -> dict[str, str]:
    """Return {port_name: bus_reported_description} for present COM ports.

    Empty dict on non-Windows or on any failure (callers degrade gracefully).
    """
    if sys.platform != "win32":
        return {}
    try:
        return _query()
    except Exception:
        # Best-effort enrichment only — never break port enumeration over it.
        log.debug("bus_reported_names lookup failed", exc_info=True)
        return {}


def _query() -> dict[str, str]:
    import ctypes
    from ctypes import POINTER, Structure, byref, c_void_p, sizeof, wintypes

    setupapi = ctypes.windll.setupapi
    ole32 = ctypes.windll.ole32

    DWORD = wintypes.DWORD
    ULONG = wintypes.ULONG
    HDEVINFO = c_void_p

    class GUID(Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8),
        ]

    class SP_DEVINFO_DATA(Structure):
        _fields_ = [
            ("cbSize", DWORD),
            ("ClassGuid", GUID),
            ("DevInst", DWORD),
            ("Reserved", POINTER(ULONG)),
        ]

    class DEVPROPKEY(Structure):
        _fields_ = [("fmtid", GUID), ("pid", ULONG)]

    def guid(s: str) -> GUID:
        g = GUID()
        if ole32.CLSIDFromString(ctypes.c_wchar_p(s), byref(g)) != 0:
            raise OSError(f"bad guid {s}")
        return g

    def propkey(fmtid: str, pid: int) -> DEVPROPKEY:
        k = DEVPROPKEY()
        k.fmtid = guid(fmtid)
        k.pid = pid
        return k

    SetupDiGetClassDevs = setupapi.SetupDiGetClassDevsW
    SetupDiGetClassDevs.argtypes = [POINTER(GUID), ctypes.c_wchar_p, c_void_p, DWORD]
    SetupDiGetClassDevs.restype = HDEVINFO

    SetupDiEnumDeviceInfo = setupapi.SetupDiEnumDeviceInfo
    SetupDiEnumDeviceInfo.argtypes = [HDEVINFO, DWORD, POINTER(SP_DEVINFO_DATA)]
    SetupDiEnumDeviceInfo.restype = wintypes.BOOL

    get_prop = setupapi.SetupDiGetDevicePropertyW
    get_prop.argtypes = [
        HDEVINFO, POINTER(SP_DEVINFO_DATA), POINTER(DEVPROPKEY),
        POINTER(ULONG), POINTER(wintypes.BYTE), DWORD, POINTER(DWORD), DWORD,
    ]
    get_prop.restype = wintypes.BOOL

    destroy = setupapi.SetupDiDestroyDeviceInfoList
    destroy.argtypes = [HDEVINFO]

    pk_bus = propkey(*_PK_BUS_DESC)
    pk_friendly = propkey(*_PK_FRIENDLY)

    def read_str(hdi, devinfo, key) -> str:
        prop_type = ULONG()
        required = DWORD()
        # First call sizes the buffer.
        get_prop(hdi, byref(devinfo), byref(key), byref(prop_type),
                 None, 0, byref(required), 0)
        if required.value == 0:
            return ""
        buf = (wintypes.BYTE * required.value)()
        if not get_prop(hdi, byref(devinfo), byref(key), byref(prop_type),
                        buf, required.value, byref(required), 0):
            return ""
        return ctypes.wstring_at(ctypes.addressof(buf)).strip()

    invalid = c_void_p(-1).value
    hdi = SetupDiGetClassDevs(byref(guid(_GUID_DEVCLASS_PORTS)), None, None,
                              _DIGCF_PRESENT)
    if not hdi or hdi == invalid:
        return {}

    out: dict[str, str] = {}
    try:
        index = 0
        while True:
            devinfo = SP_DEVINFO_DATA()
            devinfo.cbSize = sizeof(SP_DEVINFO_DATA)
            if not SetupDiEnumDeviceInfo(hdi, index, byref(devinfo)):
                break
            index += 1
            friendly = read_str(hdi, devinfo, pk_friendly)
            bus = read_str(hdi, devinfo, pk_bus)
            # friendly looks like "USB Serial Device (COM9)" — pull out COMx.
            if bus and "(COM" in friendly:
                com = friendly[friendly.rindex("(") + 1: friendly.rindex(")")]
                if com.upper().startswith("COM"):
                    out[com] = bus
    finally:
        destroy(hdi)
    return out
