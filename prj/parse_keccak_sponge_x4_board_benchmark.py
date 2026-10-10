"""Strict parser for the isolated KX41 same-boot Decaps experiment."""
from __future__ import annotations

import re

WINDOWS = (
    "software_mlkem512_decaps_3",
    "hardware_mlkem512_decaps_3",
    "timeout_fallback_mlkem512_decaps_3",
)
EXPECTED_ID = "4b583431"
EXPECTED_VERSION = "00010000"


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
        r"^KECCAK_SX4_BENCH board=not_asserted hw_compiled=1 counter_hz=(\d+)$",
        text, "KX41 benchmark header",
    )
    counter_hz = int(header.group(1))
    if not 1 <= counter_hz <= 0xFFFFFFFF:
        raise ValueError("counter frequency is outside the 32-bit UART ABI")
    if counter_hz != expected_counter_hz:
        raise ValueError(f"counter frequency mismatch: {counter_hz} != {expected_counter_hz}")
    _one(r"^KECCAK_SX4_BENCH_VALIDATION per_iteration_kat=1 identity_at_configure=1$",
         text, "per-iteration/identity validation marker")
    if len(re.findall(r"^KECCAK_SX4_BENCH_DONE$", text, re.MULTILINE)) != 1:
        raise ValueError("benchmark must have exactly one completion marker")

    identities = [tuple(part.lower() for part in pair) for pair in re.findall(
        r"^HARDWARE_CONTEXT_IDENTITY_PASS id=([0-9a-fA-F]{8}) version=([0-9a-fA-F]{8})$",
        text, re.MULTILINE,
    )]
    if identities != [(EXPECTED_ID, EXPECTED_VERSION)] * 2:
        raise ValueError("expected exactly two KX41 ID/version checks at configure")
    parsed = {}
    for label in WINDOWS:
        _one(rf"^{label}_ticks_hi=([0-9a-fA-F]{{8}})_ticks_lo=([0-9a-fA-F]{{8}})$",
             text, label + " timing")
        ticks_match = re.search(
            rf"^{label}_ticks_hi=([0-9a-fA-F]{{8}})_ticks_lo=([0-9a-fA-F]{{8}})$",
            text, re.MULTILINE,
        )
        ticks = (int(ticks_match.group(1), 16) << 32) | int(ticks_match.group(2), 16)
        if ticks == 0:
            raise ValueError(label + " timing must be nonzero")

        iteration_lines = re.findall(
            rf"^{label} KAT_ITER_PASS iteration=(\d+) tcId=(\d+)$", text, re.MULTILINE
        )
        if iteration_lines != [("0", "76"), ("1", "76"), ("2", "76")]:
            raise ValueError(label + " must prove tcId 76 KAT for each of three iterations")
        _one(rf"^{label} KAT_PASS iterations=3 tcId=76$", text, label + " aggregate KAT")
        stat_match = _one(
            rf"^{label} absorbs=(\d+) hw_absorbs=(\d+) hw_squeeze_blocks=(\d+) "
            rf"fallback=(\d+) timeout=(\d+) error=(\d+)$",
            text, label + " path counters",
        )
        absorbs, hw_absorbs, hw_squeezes, fallback, timeout, error = map(
            int, stat_match.groups()
        )
        if absorbs <= 0 or error:
            raise ValueError(label + " has no absorb work or reports a hardware error")
        parsed[label] = {
            "ticks": ticks, "counter_hz": counter_hz,
            "absorb_calls": absorbs, "hardware_absorbs": hw_absorbs,
            "hardware_squeeze_blocks": hw_squeezes,
            "software_fallbacks": fallback, "timeout_fallbacks": timeout,
            "error_fallbacks": error, "iterations": 3, "tcId": 76,
        }

    sw = parsed[WINDOWS[0]]
    hw = parsed[WINDOWS[1]]
    timeout = parsed[WINDOWS[2]]
    if (sw["hardware_absorbs"] or sw["hardware_squeeze_blocks"] or
            sw["timeout_fallbacks"] or sw["error_fallbacks"]):
        raise ValueError("software reference window used hardware or fallback path")
    if (hw["hardware_absorbs"] <= 0 or hw["hardware_squeeze_blocks"] <= 0 or
            hw["software_fallbacks"] or hw["timeout_fallbacks"] or hw["error_fallbacks"]):
        raise ValueError("normal KX41 window did not complete entirely in hardware")
    if (timeout["timeout_fallbacks"] <= 0 or timeout["software_fallbacks"] <= 0 or
            timeout["hardware_squeeze_blocks"] != 0):
        raise ValueError("forced-timeout window did not exercise software fallback")

    _one(r"^timeout_clear_status=00000000$", text, "timeout clear STATUS=0")
    _one(r"^TIMEOUT_STATUS_CLEAR_PASS$", text, "timeout STATUS clear marker")
    _one(r"^TIMEOUT_STATUS_ONLY_CHECK_NO_STATE_RESULT_READBACK$", text,
         "timeout clear readback scope marker")
    sw_ticks, hw_ticks = sw["ticks"], hw["ticks"]
    return {
        "hardware_path_compiled": True,
        "counter_hz": counter_hz,
        "windows": parsed,
        "hardware_over_software_ratio": hw_ticks / sw_ticks,
        "timeout_fallback_checked_status_zero": True,
        "timeout_clear_scope": "STATUS register only; STATE/OUTPUT were not read back",
        "kat_scope": "tcId 76 shared secret compared after each of three Decaps per window",
    }
