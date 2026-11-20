"""Sync host driver: port discovery and the session state machine.

Depends on ``ppk2.protocol`` and ``serial`` (pyserial).
"""

from ppk2.client.discovery import (
    DEFAULT_DISCOVERY_TIMEOUT_S,
    Ambiguous,
    DataPortNotFound,
    DiscoveryError,
    NotFound,
    PortInfo,
    Ppk2Listing,
    find_ppk2,
    find_ppk2_by_serial,
    list_ppk2s,
)
from ppk2.client.session import (
    VOLTAGE_LIMIT_HARDWARE_MAX_MV,
    VOLTAGE_LIMIT_HARDWARE_MIN_MV,
    HandshakeFailed,
    Mode,
    SerialIOError,
    Session,
    SessionError,
)

__all__ = [
    "DEFAULT_DISCOVERY_TIMEOUT_S",
    "VOLTAGE_LIMIT_HARDWARE_MAX_MV",
    "VOLTAGE_LIMIT_HARDWARE_MIN_MV",
    "Ambiguous",
    "DataPortNotFound",
    "DiscoveryError",
    "HandshakeFailed",
    "Mode",
    "NotFound",
    "PortInfo",
    "Ppk2Listing",
    "SerialIOError",
    "Session",
    "SessionError",
    "find_ppk2",
    "find_ppk2_by_serial",
    "list_ppk2s",
]
