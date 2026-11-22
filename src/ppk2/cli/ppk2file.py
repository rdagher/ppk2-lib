"""``.ppk2`` session files, as saved and loaded by Nordic's Power Profiler app.

A ``.ppk2`` file is a zip of three files (the app's README, "File
format", and its source at v4.4.1):

- ``session.raw``: 6 bytes per sample. The current in µA as a
  little-endian float32, then a big-endian uint16 with two bits per
  digital channel (``01`` low, ``10`` high), D0 in the lowest pair.
- ``minimap.raw``: JSON min/max envelope of the whole trace, at most
  10 000 points; the app draws its overview strip from it.
- ``metadata.json``: sample rate and format version.

Nordic gives no guarantee that the format stays the same.
"""

import errno
import json
import struct
import sys
import zipfile
from math import isnan
from pathlib import Path

#: Sample rates the app can replay.
SAMPLE_RATES = (1, 10, 100, 1_000, 10_000, 100_000)

_FORMAT_VERSION = 2
_MINIMAP_POINTS = 10_000
_MINIMAP_FLOOR_NA = 200.0  # the app floors its overview there, for a log axis


def _bit_pairs(logic: int) -> int:
    """Spread 8 logic bits over 16: ``01`` for a low channel, ``10`` for a high one."""
    return sum(1 << (2 * ch + ((logic >> ch) & 1)) for ch in range(8))


# One frame is the current then the bit pairs. The pairs are big-endian
# on disk, so the table stores them byte-swapped for the little-endian pack.
_FRAME = struct.Struct("<fH")
_PAIRS = tuple(int.from_bytes(_bit_pairs(b).to_bytes(2, "big"), "little") for b in range(256))


class _Minimap:
    """Min/max envelope that halves its resolution each time it fills up.

    Keeps the same books as the app's own overview buffer, so the saved
    state is what the app would have written for the same samples.
    """

    def __init__(self) -> None:
        self._lo: list[list[float]] = []  # [time in µs, current in nA]
        self._hi: list[list[float]] = []
        self._per_point = 1  # samples folded into each point
        self._in_last = 0  # samples in the newest point so far

    def add(self, current_ua: float, t_us: float) -> None:
        if self._in_last == 0:
            self._lo.append([t_us, sys.float_info.max])
            self._hi.append([t_us, -sys.float_info.max])
        lo, hi = self._lo[-1], self._hi[-1]

        self._in_last += 1
        weight = 1.0 / self._in_last
        lo[0] = hi[0] = t_us * weight + lo[0] * (1.0 - weight)

        na = current_ua * 1000.0
        if na < _MINIMAP_FLOOR_NA:
            na = _MINIMAP_FLOOR_NA
        if not isnan(na):  # a lost sample has no value to fold in
            lo[1] = min(lo[1], na)
            hi[1] = max(hi[1], na)

        if self._in_last == self._per_point:
            self._in_last = 0
        if len(self._lo) == _MINIMAP_POINTS:
            self._fold()

    def _fold(self) -> None:
        """Merge neighbouring points pairwise."""
        self._per_point *= 2
        self._lo = [
            [(a[0] + b[0]) / 2, min(a[1], b[1])]
            for a, b in zip(self._lo[::2], self._lo[1::2], strict=True)
        ]
        self._hi = [
            [(a[0] + b[0]) / 2, max(a[1], b[1])]
            for a, b in zip(self._hi[::2], self._hi[1::2], strict=True)
        ]

    def to_json(self) -> dict[str, object]:
        return {
            "lastElementFoldCount": self._in_last,
            "data": {
                "length": len(self._lo),
                "min": [{"x": x, "y": y} for x, y in self._lo],
                "max": [{"x": x, "y": y} for x, y in self._hi],
            },
            "maxNumberOfElements": _MINIMAP_POINTS,
            "numberOfTimesToFold": self._per_point,
        }


class Ppk2FileWriter:
    """Write a stream of samples to a ``.ppk2`` file; use as a context manager.

    Leaving the block writes the file, even on an exception: an
    interrupted capture still yields a valid, shorter session. The file
    appears only once it is complete, and not at all for a capture with
    no sample. Until then the frames are in ``<name>.frames`` next to
    it, and stay there if the file cannot be completed.
    """

    def __init__(self, path: Path, samples_per_second: int = 100_000) -> None:
        if samples_per_second not in SAMPLE_RATES:
            raise ValueError(f"unsupported sample rate {samples_per_second} (app: {SAMPLE_RATES})")
        self._path = path
        self._rate = samples_per_second
        # Frames go to a scratch file first, so the zip knows its size up front.
        self._frames_path = path.with_name(path.name + ".frames")
        if self._frames_path.exists():
            # What a run that failed left behind is all that is left of
            # it: not overwritten.
            raise FileExistsError(
                errno.EEXIST,
                "left by a run that did not finish: move or delete it",
                str(self._frames_path),
            )
        self._raw = self._frames_path.open("wb")
        self._minimap = _Minimap()
        self._closed = False
        #: Samples written so far, lost ones included.
        self.count = 0

    def __enter__(self) -> "Ppk2FileWriter":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def add(self, current_ua: float, logic: int) -> None:
        """Append one sample. NaN is stored as it is: TraceFile replaces it before."""
        if current_ua < 0.2:
            current_ua = 0.0  # the app reads anything below 0.2 µA as zero
        self._raw.write(_FRAME.pack(current_ua, _PAIRS[logic & 0xFF]))
        self._minimap.add(current_ua, self.count * 1e6 / self._rate)
        self.count += 1

    def discard(self) -> None:
        """Give up: write no file and drop the frames."""
        if self._closed:
            return
        self._closed = True
        self._raw.close()
        self._frames_path.unlink(missing_ok=True)

    def close(self) -> None:
        """Zip the three files, move the result into place, remove the scratch file."""
        if self._closed:
            return
        self._closed = True
        self._raw.close()
        if self.count == 0:
            self._frames_path.unlink(missing_ok=True)
            return
        metadata = {
            "metadata": {"samplesPerSecond": self._rate},
            "formatVersion": _FORMAT_VERSION,
        }
        partial = self._path.with_name(self._path.name + ".part")
        try:
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                zf.write(self._frames_path, "session.raw")
                zf.writestr("minimap.raw", json.dumps(self._minimap.to_json()))
                zf.writestr("metadata.json", json.dumps(metadata))
            partial.replace(self._path)
        except BaseException:
            partial.unlink(missing_ok=True)  # the frames file stays: nothing is lost
            raise
        self._frames_path.unlink(missing_ok=True)
