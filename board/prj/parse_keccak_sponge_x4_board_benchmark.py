"""Strict parser for a same-boot, full 60-vector KX41 board KAT run."""
from __future__ import annotations

import re

WINDOWS = ("software", "hardware", "timeout_fallback")
EXPECTED_ID = "4b583431"
EXPECTED_VERSION = "00010000"
EXPECTED_CASES = tuple(
    [("keygen", tcid) for tcid in range(1, 26)]
    + [("encapsulation", tcid) for tcid in range(1, 26)]
    + [("decapsulation", tcid) for tcid in range(76, 86)]
)


def _one(pattern: str, text: str, name: str) -> re.Match[str]:
    matches = list(re.finditer(pattern, text, re.MULTILINE))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name}, found {len(matches)}")
    return matches[0]


def parse_log(text: str, *, expected_counter_hz: int) -> dict:
    text = text.replace("\r", "")
    if not expected_counter_hz or expected_counter_hz > 0xFFFFFFFF:
        raise ValueError("expected counter frequency must fit the 32-bit UART ABI")
    if re.search(r"(?:FAIL|_ERROR|WATCHDOG|HARDWARE_CONTEXT_IDENTITY_FAIL)", text):
        raise ValueError("failure marker present in UART log")
    header = _one(
        r"^KX41_BENCH board=not_asserted hw_compiled=1 counter_hz=(\d+) "
        r"vectors=60 keygen=25 encapsulation=25 decapsulation=10$",
        text, "KX41 benchmark header",
    )
    counter_hz = int(header.group(1))
    if not 1 <= counter_hz <= 0xFFFFFFFF:
        raise ValueError("counter frequency is outside the 32-bit UART ABI")
    if counter_hz != expected_counter_hz:
        raise ValueError(f"counter frequency mismatch: {counter_hz} != {expected_counter_hz}")
    _one(r"^KX41_BENCH_VALIDATION per_vector_kat=1 identity_at_window=1$",
         text, "per-vector/identity validation marker")
    if len(re.findall(r"^KX41_BENCH_DONE$", text, re.MULTILINE)) != 1:
        raise ValueError("benchmark must have exactly one completion marker")

    identity_matches = list(re.finditer(
        r"^HARDWARE_CONTEXT_IDENTITY_PASS window=(hardware|timeout_fallback) "
        r"id=([0-9a-fA-F]{8}) version=([0-9a-fA-F]{8})$",
        text, re.MULTILINE,
    ))
    identities = [(m.group(1), m.group(2).lower(), m.group(3).lower())
                  for m in identity_matches]
    if identities != [("hardware", EXPECTED_ID, EXPECTED_VERSION),
                      ("timeout_fallback", EXPECTED_ID, EXPECTED_VERSION)]:
        raise ValueError("expected KX41 ID/version checks bound to both hardware windows")
    identity_by_window = {m.group(1): m for m in identity_matches}

    expected = set(EXPECTED_CASES)
    parsed = {}
    for window in WINDOWS:
        start_match = _one(rf"^KX41_WINDOW_START window={window}$", text,
                           window + " start")
        ticks_match = _one(
            rf"^KX41_WINDOW_TICKS window={window} hi=([0-9a-fA-F]{{8}}) "
            r"lo=([0-9a-fA-F]{8})$", text, window + " timing"
        )
        ticks = (int(ticks_match.group(1), 16) << 32) | int(ticks_match.group(2), 16)
        if ticks == 0:
            raise ValueError(window + " timing must be nonzero")
        if start_match.start() >= ticks_match.start():
            raise ValueError(window + " start marker must precede its timing result")
        if window != "software":
            identity = identity_by_window[window]
            if not start_match.start() < identity.start() < ticks_match.start():
                raise ValueError(window + " ID/version check is not inside its window setup")
        lines = re.findall(
            rf"^KX41_VECTOR_PASS window={window} operation=([a-z]+) tcId=(\d+)$",
            text, re.MULTILINE,
        )
        cases = [(operation, int(tcid)) for operation, tcid in lines]
        if len(cases) != 60 or set(cases) != expected or len(set(cases)) != 60:
            raise ValueError(window + " must prove all 60 unique expected KAT vectors exactly once")

        summary = _one(
            rf"^KX41_WINDOW_SUMMARY window={window} vectors=(\d+) absorbs=(\d+) "
            r"hw_absorbs=(\d+) hw_squeeze_blocks=(\d+) fallback=(\d+) "
            r"timeout=(\d+) error=(\d+) timeout_status_zero_vectors=(\d+)$",
            text, window + " path counters",
        )
        vectors, absorbs, hw_absorbs, hw_squeezes, fallback, timeout, error, status_zero = map(
            int, summary.groups()
        )
        if vectors != 60 or absorbs <= 0 or error:
            raise ValueError(window + " has invalid vector count, no absorb work, or errors")
        parsed[window] = {
            "ticks": ticks, "counter_hz": counter_hz, "unique_vectors": vectors,
            "absorb_calls": absorbs, "hardware_absorbs": hw_absorbs,
            "hardware_squeeze_blocks": hw_squeezes,
            "software_fallbacks": fallback, "timeout_fallbacks": timeout,
            "error_fallbacks": error, "timeout_status_zero_vectors": status_zero,
            "cases": cases,
        }

    sw, hw, timeout = (parsed[k] for k in WINDOWS)
    if (sw["hardware_absorbs"] or sw["hardware_squeeze_blocks"] or
            sw["software_fallbacks"] or
            sw["timeout_fallbacks"] or sw["error_fallbacks"] or sw["timeout_status_zero_vectors"]):
        raise ValueError("software reference window used hardware or a fallback")
    if (hw["hardware_absorbs"] <= 0 or hw["hardware_squeeze_blocks"] <= 0 or
            hw["software_fallbacks"] or hw["timeout_fallbacks"]):
        raise ValueError("normal KX41 window did not stay on hardware or had fallbacks")
    if timeout["timeout_fallbacks"] < 60 or timeout["hardware_squeeze_blocks"] or \
            timeout["timeout_status_zero_vectors"] != 60:
        raise ValueError("forced-timeout window did not clear STATUS after all 60 KATs")

    _one(r"^KX41_FINAL_STATUS=00000000$", text, "final STATUS=0")
    _one(r"^KX41_FINAL_STATUS_CLEAR_PASS$", text, "final status clear marker")
    _one(r"^KX41_TIMEOUT_MEMORY_READBACK=NOT_PERFORMED$", text,
         "timeout memory readback scope marker")
    return {
        "hardware_path_compiled": True,
        "counter_hz": counter_hz,
        "windows": parsed,
        "hardware_over_software_ratio": hw["ticks"] / sw["ticks"],
        "timeout_status_zero_all_vectors": True,
        "timeout_clear_scope": "STATUS register only; STATE/OUTPUT were not read back",
        "kat_scope": "60 unique ML-KEM-512 keygen/encapsulation/decapsulation vectors per window",
    }
