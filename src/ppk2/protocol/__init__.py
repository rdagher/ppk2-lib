"""Pure protocol primitives: opcodes, metadata parser, sample decoder, stream.

Stdlib-only; no I/O. The top-level ``ppk2`` package re-exports the
items you'd typically import from here.
"""

from ppk2.protocol.calibration import current_micro_amps
from ppk2.protocol.metadata import (
    NUM_RANGES,
    CalibrationCoefficients,
    InvalidValue,
    MetadataError,
    MissingEnd,
    MissingField,
    RangeArray,
    parse_metadata,
)
from ppk2.protocol.opcode import Opcode
from ppk2.protocol.sample import RawSample, decode_sample, decode_sample_bytes
from ppk2.protocol.stream import (
    DEFAULT_SPIKE_FILTER_ALPHA,
    DEFAULT_SPIKE_FILTER_ALPHA5,
    DEFAULT_SPIKE_FILTER_SAMPLES,
    MAX_BUFFERED_CORRUPTED,
    Sample,
    SpikeFilter,
    StreamParser,
)

__all__ = [
    "DEFAULT_SPIKE_FILTER_ALPHA",
    "DEFAULT_SPIKE_FILTER_ALPHA5",
    "DEFAULT_SPIKE_FILTER_SAMPLES",
    "MAX_BUFFERED_CORRUPTED",
    "NUM_RANGES",
    "CalibrationCoefficients",
    "InvalidValue",
    "MetadataError",
    "MissingEnd",
    "MissingField",
    "Opcode",
    "RangeArray",
    "RawSample",
    "Sample",
    "SpikeFilter",
    "StreamParser",
    "current_micro_amps",
    "decode_sample",
    "decode_sample_bytes",
    "parse_metadata",
]
