from __future__ import annotations


def extract_definite_block_payload(raw: bytes) -> bytes:
    """Return the payload from an IEEE 488.2 definite-length binary block."""
    if not raw.startswith(b"#"):
        raise ValueError(f"Unexpected binary block header: {raw[:32]!r}")

    if len(raw) < 2:
        raise ValueError("Incomplete binary block header")

    n_digits = int(raw[1:2])
    if n_digits <= 0:
        raise ValueError("Indefinite-length binary blocks are not supported")

    length_end = 2 + n_digits
    if len(raw) < length_end:
        raise ValueError("Incomplete binary block length")

    n_bytes = int(raw[2:length_end])
    payload_start = length_end
    payload_end = payload_start + n_bytes
    if len(raw) < payload_end:
        raise ValueError(
            f"Incomplete binary block payload: expected {n_bytes} bytes, "
            f"got {max(0, len(raw) - payload_start)}"
        )

    return raw[payload_start:payload_end]
