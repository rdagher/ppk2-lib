"""Python library + CLI for Nordic's Power Profiler Kit II (PPK2).

Three layers:

- ``ppk2.protocol``: pure wire-protocol primitives, stdlib-only.
- ``ppk2.client``: sync host driver on top of ``pyserial``.
- ``ppk2.cli``: the ``ppk2`` binary, internal to the package.

For library use, import from this top level:

>>> from ppk2 import StreamParser, parse_metadata, Sample  # protocol layer
>>> from ppk2 import Session, find_ppk2  # client layer
"""

from ppk2.client import (
    VOLTAGE_LIMIT_HARDWARE_MAX_MV,
    VOLTAGE_LIMIT_HARDWARE_MIN_MV,
    Ambiguous,
    DataPortNotFound,
    DiscoveryError,
    HandshakeFailed,
    Mode,
    NotFound,
    PortInfo,
    Ppk2Listing,
    SerialIOError,
    Session,
    SessionError,
    find_ppk2,
    find_ppk2_by_serial,
    list_ppk2s,
)
from ppk2.protocol import (
    DEFAULT_SPIKE_FILTER_ALPHA,
    DEFAULT_SPIKE_FILTER_ALPHA5,
    DEFAULT_SPIKE_FILTER_SAMPLES,
    MAX_BUFFERED_CORRUPTED,
    NUM_RANGES,
    CalibrationCoefficients,
    InvalidValue,
    MetadataError,
    MissingEnd,
    MissingField,
    Opcode,
    RangeArray,
    RawSample,
    Sample,
    SpikeFilter,
    StreamParser,
    current_micro_amps,
    decode_sample,
    decode_sample_bytes,
    parse_metadata,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_SPIKE_FILTER_ALPHA",
    "DEFAULT_SPIKE_FILTER_ALPHA5",
    "DEFAULT_SPIKE_FILTER_SAMPLES",
    "MAX_BUFFERED_CORRUPTED",
    "NUM_RANGES",
    "VOLTAGE_LIMIT_HARDWARE_MAX_MV",
    "VOLTAGE_LIMIT_HARDWARE_MIN_MV",
    "Ambiguous",
    "CalibrationCoefficients",
    "DataPortNotFound",
    "DiscoveryError",
    "HandshakeFailed",
    "InvalidValue",
    "MetadataError",
    "MissingEnd",
    "MissingField",
    "Mode",
    "NotFound",
    "Opcode",
    "PortInfo",
    "Ppk2Listing",
    "RangeArray",
    "RawSample",
    "Sample",
    "SerialIOError",
    "Session",
    "SessionError",
    "SpikeFilter",
    "StreamParser",
    "__version__",
    "current_micro_amps",
    "decode_sample",
    "decode_sample_bytes",
    "find_ppk2",
    "find_ppk2_by_serial",
    "list_ppk2s",
    "parse_metadata",
]
