"""Validate and summarize raw UART output from the isolated Keccak board benchmark."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


HEADER_RE = re.compile(
    r"^KECCAK_BENCH board=not_asserted hw_compiled=([01]) counter_hz=(\d+)\s*$",
    re.MULTILINE,
)
TICKS_RE = re.compile(
    r"^([A-Za-z0-9_]+)_ticks_hi=([0-9a-fA-F]{1,8})_ticks_lo=([0-9a-fA-F]{1,8})\s*$",
    re.MULTILINE,
)
STATS_RE = re.compile(
    r"^([A-Za-z0-9_]+) dispatch=(\d+) hw=(\d+) fallback=(\d+)\s*$",
    re.MULTILINE,
)


class ParseError(ValueError):
    """Raised when the UART transcript cannot establish a complete valid run."""


def _one(match_list: list[re.Match[str]], description: str) -> re.Match[str]:
    if len(match_list) != 1:
        raise ParseError(f"expected exactly one {description}, found {len(match_list)}")
    return match_list[0]


def parse_log(text: str, expected_counter_hz: int | None = None) -> dict[str, Any]:
    """Parse one complete firmware boot transcript and enforce its path checks."""
    header = _one(list(HEADER_RE.finditer(text)), "benchmark header")
    hw_enabled = header.group(1) == "1"
    frequency = int(header.group(2))
    if frequency < 10_000_000 or frequency > 1_000_000_000 or frequency > 0xFFFFFFFF:
        raise ParseError("counter_hz is outside the plausible 32-bit Cortex-A9 timer ABI range")
    if expected_counter_hz is not None and frequency != expected_counter_hz:
        raise ParseError(
            f"counter_hz {frequency} does not match expected XTime frequency {expected_counter_hz}"
        )

    if len(re.findall(r"^KECCAK_BENCH_DONE\s*$", text, re.MULTILINE)) != 1:
        raise ParseError("missing or repeated KECCAK_BENCH_DONE")
    failure_markers = re.findall(
        r"^(?:[A-Za-z0-9_]+ (?:DECAPS_FAIL|KAT_FAIL|PATH_COUNT_FAIL)|"
        r"HARDWARE_DISABLED|HARDWARE_PERMUTE_FAIL)\b.*$",
        text,
        re.MULTILINE,
    )
    if failure_markers:
        raise ParseError("firmware reported failure: " + failure_markers[0])
    if "TIMEOUT_DEVICE_ZEROIZE_PASS" in text or "timeout_clear_zero_or=" in text:
        raise ParseError("legacy full-device zeroize claims are not accepted by this parser")

    ticks: dict[str, dict[str, int]] = {}
    for match in TICKS_RE.finditer(text):
        label = match.group(1)
        if label in ticks:
            raise ParseError(f"repeated timing label: {label}")
        hi, lo = int(match.group(2), 16), int(match.group(3), 16)
        ticks[label] = {"ticks": (hi << 32) | lo}

    stats: dict[str, dict[str, int]] = {}
    for match in STATS_RE.finditer(text):
        label = match.group(1)
        if label in stats:
            raise ParseError(f"repeated dispatch stats label: {label}")
        stats[label] = {
            "dispatch": int(match.group(2)),
            "hardware": int(match.group(3)),
            "fallback": int(match.group(4)),
        }

    def check_decapsulation(label: str, path: str) -> None:
        if label not in ticks or label not in stats:
            raise ParseError(f"missing timing or post-KAT stats for {label}")
        timing_pos = text.find(label + "_ticks_hi=")
        stats_pos = text.find(label + " dispatch=")
        if timing_pos < 0 or stats_pos <= timing_pos:
            raise ParseError(f"{label} stats do not follow its timed KAT run")
        count = stats[label]
        if count["dispatch"] <= 0:
            raise ParseError(f"{label} had no Keccak permutation dispatches")
        if path == "software" and not (
            count["hardware"] == 0 and count["fallback"] == count["dispatch"]
        ):
            raise ParseError(f"{label} did not stay on the software fallback path")
        if path == "hardware" and not (
            count["hardware"] == count["dispatch"] and count["dispatch"] > 0
            and count["fallback"] == 0
        ):
            raise ParseError(f"{label} did not complete all dispatches in hardware")
        if path == "timeout" and not (
            count["hardware"] == 0 and count["fallback"] == count["dispatch"]
        ):
            raise ParseError(f"{label} did not fall back for every dispatch")

    check_decapsulation("software_mlkem512_decaps_3", "software")
    if hw_enabled:
        check_decapsulation("hardware_mlkem512_decaps_3", "hardware")
        check_decapsulation("timeout_fallback_mlkem512_decaps_3", "timeout")
        gate = re.search(
            r"^hardware_gate id=([0-9a-fA-F]{8}) version=([0-9a-fA-F]{8}) "
            r"expected=([0-9a-fA-F]{8})/([0-9a-fA-F]{8})\s*$",
            text,
            re.MULTILINE,
        )
        if gate is None or (gate.group(1).lower(), gate.group(2).lower()) != (
            gate.group(3).lower(), gate.group(4).lower()
        ):
            raise ParseError("missing or failed hardware ID/version gate")
        required = (
            "mmio_transfer_50_state_write",
            "mmio_transfer_50_result_read_after_done",
            "mmio_transfer_50_write_50_read_excluding_permutation",
            "hardware_single_permutation_including_mmio",
        )
        missing = [label for label in required if label not in ticks]
        if missing:
            raise ParseError("missing hardware measurements: " + ", ".join(missing))
        if ticks["mmio_transfer_50_write_50_read_excluding_permutation"]["ticks"] != (
            ticks["mmio_transfer_50_state_write"]["ticks"]
            + ticks["mmio_transfer_50_result_read_after_done"]["ticks"]
        ):
            raise ParseError("combined MMIO transfer ticks do not equal the timed write/read intervals")
        if not re.search(r"^MMIO_TRANSFER_RESULT_READ_GATED_DONE_PASS\s*$", text, re.MULTILINE):
            raise ParseError("missing DONE-gated RESULT read marker")
        status = re.search(r"^timeout_clear_status=([0-9a-fA-F]{8})\s*$", text, re.MULTILINE)
        if status is None or int(status.group(1), 16) != 0:
            raise ParseError("timeout STATUS readback was missing or nonzero")
        if not re.search(r"^TIMEOUT_STATUS_CLEAR_PASS\s*$", text, re.MULTILINE):
            raise ParseError("missing timeout STATUS clear pass marker")
        if not re.search(r"^TIMEOUT_STATUS_ONLY_CHECK_NO_STATE_RESULT_READBACK\s*$", text, re.MULTILINE):
            raise ParseError("missing marker limiting timeout check to STATUS only")
        if "HARDWARE_NOT_COMPILED" in text:
            raise ParseError("HW-enabled image reported that hardware was not compiled")
    elif "HARDWARE_NOT_COMPILED no_mmio_probe" not in text:
        raise ParseError("SW-only image did not confirm MMIO probing was disabled")

    measurements: dict[str, dict[str, float | int]] = {}
    for label, value in ticks.items():
        count = value["ticks"]
        measurements[label] = {
            "ticks": count,
            "seconds": count / frequency,
        }

    comparison = None
    if hw_enabled:
        sw_ticks = ticks["software_mlkem512_decaps_3"]["ticks"]
        hw_ticks = ticks["hardware_mlkem512_decaps_3"]["ticks"]
        comparison = {
            "decapsulations_per_window": 3,
            "software_average_seconds": sw_ticks / frequency / 3,
            "hardware_average_seconds": hw_ticks / frequency / 3,
            "software_over_hardware_ratio": sw_ticks / hw_ticks if hw_ticks else None,
            "comparison_scope": "same firmware boot; complete ML-KEM decapsulation including Keccak MMIO and fallback dispatch overhead",
        }

    return {
        "board_identity_asserted_by_firmware": False,
        "hardware_path_compiled": hw_enabled,
        "counter_hz_from_firmware": frequency,
        "frequency_source": "runtime COUNTS_PER_SECOND printed by XTime firmware; optionally checked against floor(manifest CPU clock / 2)",
        "measurements": measurements,
        "dispatch_stats": stats,
        "timeout_clear_status": int(status.group(1), 16) if hw_enabled else None,
        "timeout_clear_scope": "STATUS register only; STATE/RESULT readback was not attempted" if hw_enabled else None,
        "kat_evidence": "each decapsulation timing is followed by dispatch stats; firmware emits those stats only after the shared-secret KAT comparison succeeds",
        "comparison": comparison,
        "complete": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("uart_log", type=Path, help="saved raw UART transcript for exactly one firmware boot")
    parser.add_argument("--manifest", type=Path,
                        help="new matching firmware build manifest; checks counter_hz against cpu_clock_hz // 2")
    args = parser.parse_args()
    try:
        expected_counter_hz = None
        if args.manifest:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            cpu_hz = int(manifest["cpu_clock_hz_from_new_xsa_bsp"])
            expected_counter_hz = cpu_hz // 2
        result = parse_log(
            args.uart_log.read_text(encoding="utf-8", errors="replace"),
            expected_counter_hz=expected_counter_hz,
        )
    except (OSError, ParseError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
