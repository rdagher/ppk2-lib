# Test fixtures

Captured-hardware artefacts used by the protocol layer's tests. All
are small enough to vendor (~17 KB total); the project depends on
nothing outside this repo to run its test suite.

| File | What | Used by |
|---|---|---|
| [`metadata.raw`](metadata.raw) | 1032 bytes — `GET_META_DATA` response captured from a real PPK2 (captured with a DWM3001CDK dev kit as the DUT, 2026-06-05). | [`tests/protocol/test_metadata.py`](../protocol/test_metadata.py), [`tests/protocol/test_calibration.py`](../protocol/test_calibration.py) |
| [`metadata.parsed.json`](metadata.parsed.json) | Reference parse of `metadata.raw` (R / GS / GI / O / S / I / UG arrays + HW + IA + Calibrated). | [`tests/protocol/test_metadata.py`](../protocol/test_metadata.py) (ground-truth byte-for-byte comparison) |
| [`stream_4000.bin`](stream_4000.bin) | First 4 000 bytes (= 1 000 samples = 10 ms) of a 30 s sample stream from the same bench. | [`tests/protocol/test_stream.py`](../protocol/test_stream.py) (parity test) |
| [`parsed_1000.csv`](parsed_1000.csv) | First 1 000 rows of the corresponding parsed-CSV ground truth from the upstream Python reference, IRNAS `ppk2-api-python`. | [`tests/protocol/test_stream.py`](../protocol/test_stream.py) (per-sample current comparison within ±0.01 µA) |

## Provenance

`metadata.raw` / `stream_*.bin` / `parsed_*.csv` originate from
captures the project author ran on a known-good bench setup; they were
parsed by a known-good independent Python implementation (IRNAS
`ppk2-api-python`) to produce the JSON / CSV ground truth. The fixtures are committed to make the
test suite reproducible — anyone can run `just test` without needing
hardware. The HIL test tier (`just test-hw`) re-validates the same
contract against fresh captures.
