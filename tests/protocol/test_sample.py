"""Sample-word bit-extraction tests."""

from ppk2 import decode_sample, decode_sample_bytes

# A sample word captured from a PPK2.
_CAPTURED_WORD = 0x015C_0097


def test_captured_word_decodes_to_documented_fields() -> None:
    s = decode_sample(_CAPTURED_WORD)
    assert s.adc_14 == 151
    assert s.range == 0
    assert s.counter == 23
    assert s.logic == 0x01
    assert s.range_valid()
    assert s.pin(0)
    assert not s.pin(1)


def test_bytes_path_matches_int_path() -> None:
    bytes_le = _CAPTURED_WORD.to_bytes(4, "little")
    assert decode_sample(_CAPTURED_WORD) == decode_sample_bytes(bytes_le)


def test_out_of_range_range_index_is_flagged() -> None:
    bad = decode_sample(0xFFFF_FFFF)
    assert bad.range == 7
    assert not bad.range_valid()


def test_all_fields_at_in_spec_maximum() -> None:
    # adc_14 = 16_383, range = 4, counter = 63, logic = 0xFF.
    # See the bit layout in ``ppk2.protocol.sample``'s module docstring.
    raw = 0xFFFD_3FFF
    s = decode_sample(raw)
    assert s.adc_14 == 16_383
    assert s.range == 4
    assert s.counter == 63
    assert s.logic == 0xFF


def test_decode_sample_bytes_rejects_wrong_length() -> None:
    import pytest

    with pytest.raises(ValueError):
        decode_sample_bytes(b"\x01\x02\x03")  # 3 bytes
