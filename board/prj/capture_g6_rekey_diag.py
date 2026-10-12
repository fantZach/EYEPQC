"""Take a bounded, read-only AP0 snapshot of G6 HELLO/ACK diagnostics."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TCL = ROOT / 'board/prj/read_g6_rekey_diag.tcl'
PHASES = {'WAIT_HELLO', 'WAIT_KEM', 'WAIT_FINISHED', 'WAIT_START', 'STREAM', 'FAULT'}
HEX_FIELDS = {
    'hello_ack_send_status', 'cleanup_last_result', 'ep1_prime', 'ep1_ready',
    'epcr1', 'ep1_completion', 'ep1_flush', 'tx_completion_status',
    'tx_completion_token', 'tx_completion_match_flags',
}
INTEGER_FIELDS = {
    'abi', 'sequence', 'phase_id', 'last_control_type', 'received_controls',
    'hello_attempts', 'hello_ack_send_attempts', 'cleanup_count',
    'usb_configured', 'usb_dtr', 'connection_epoch', 'tx_ready',
    'rx_bytes_buffered', 'rx_head', 'rx_tail', 'rx_bad', 'control_errors',
    'fatal_errors', 'transport_errors', 'tx_completion_count',
    'tx_completion_residual', 'tx_completion_requested', 'tx_completion_expected',
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_snapshot(stdout: str) -> dict:
    match = re.search(r'^G6_REKEY_DIAG (.+)$', stdout, re.MULTILINE)
    if not match or 'G6_REKEY_DIAG_READ_OK' not in stdout:
        raise ValueError('XSDB output has no complete G6_REKEY_DIAG snapshot')
    fields = {}
    for token in match.group(1).split():
        if '=' not in token:
            raise ValueError('Malformed G6_REKEY_DIAG field')
        name, value = token.split('=', 1)
        if name in fields:
            raise ValueError('Duplicate G6_REKEY_DIAG field: ' + name)
        fields[name] = value
    required_fields = INTEGER_FIELDS | HEX_FIELDS | {'phase', 'scope', 'payload_or_keys'}
    if not required_fields.issubset(fields):
        raise ValueError('G6_REKEY_DIAG snapshot is missing required fields')
    if fields['phase'] not in PHASES or fields['scope'] != 'PS_AP0_DDR_diagnostic_only' or \
            fields['payload_or_keys'] != 'not_read':
        raise ValueError('G6_REKEY_DIAG scope or phase is invalid')
    parsed = {'phase': fields['phase'], 'scope': fields['scope'],
              'payload_or_keys': fields['payload_or_keys']}
    for name in INTEGER_FIELDS:
        try:
            value = int(fields[name], 10)
        except ValueError as exc:
            raise ValueError('Invalid decimal G6_REKEY_DIAG field: ' + name) from exc
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError('G6_REKEY_DIAG field is outside uint32: ' + name)
        parsed[name] = value
    for name in HEX_FIELDS:
        try:
            value = int(fields[name], 16)
        except ValueError as exc:
            raise ValueError('Invalid hexadecimal G6_REKEY_DIAG field: ' + name) from exc
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError('G6_REKEY_DIAG field is outside uint32: ' + name)
        parsed[name] = value
    if parsed['abi'] != 2 or parsed['phase_id'] >= len(PHASES):
        raise ValueError('G6_REKEY_DIAG ABI or phase ID is invalid')
    if parsed['phase'] != list(('WAIT_HELLO', 'WAIT_KEM', 'WAIT_FINISHED',
                                'WAIT_START', 'STREAM', 'FAULT'))[parsed['phase_id']]:
        raise ValueError('G6_REKEY_DIAG phase name and phase ID differ')
    for name in ('usb_configured', 'usb_dtr', 'tx_ready', 'rx_bad'):
        if parsed[name] not in (0, 1):
            raise ValueError('G6_REKEY_DIAG boolean is outside range: ' + name)
    if any(parsed[name] > 2047 for name in ('rx_bytes_buffered', 'rx_head', 'rx_tail')):
        raise ValueError('G6_REKEY_DIAG receive ring value is outside bounds')
    if parsed['tx_completion_status'] not in (0, 3, 4, 5, 0xFFFFFFFF) or \
            parsed['tx_completion_match_flags'] > 31:
        raise ValueError('G6_REKEY_DIAG TX completion status is outside bounds')
    for name in ('tx_completion_residual', 'tx_completion_requested',
                 'tx_completion_expected'):
        if parsed[name] != 0xFFFFFFFF and parsed[name] > 16384:
            raise ValueError('G6_REKEY_DIAG TX length is outside bounds: ' + name)
    return parsed


def load_build_identity(workspace: Path) -> tuple[dict, int, int]:
    manifest_path = workspace / 'g6_usb_manifest.json'
    elf_path = workspace / 'g6_usb/build/g6_usb.elf'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    elf_hash = digest(elf_path)
    if manifest.get('artifacts', {}).get('g6_usb/build/g6_usb.elf') != elf_hash:
        raise ValueError('G6 ELF does not match its manifest')
    owned = manifest.get('owned', {}).get('g6_rekey_diagnostic')
    if not owned:
        raise ValueError('Build has no owned G6 rekey diagnostic symbol')
    address = int(owned['address'], 0) if isinstance(owned['address'], str) else int(owned['address'])
    size = int(owned['size'])
    if size != 144 or address < 0x00100000 or address % 64 or address + size > 0x40000000:
        raise ValueError('Build manifest has an invalid G6 rekey diagnostic range')
    identity = {
        'manifest_sha256': digest(manifest_path),
        'elf_sha256': elf_hash,
        'xsa_sha256': manifest.get('xsa_sha256'),
    }
    if not identity['xsa_sha256']:
        raise ValueError('Build manifest has no XSA identity')
    return identity, address, size


def capture(workspace: Path, tool_root: Path, output_prefix: Path) -> dict:
    identity, address, size = load_build_identity(workspace)
    xsdb = tool_root / 'Vivado/bin/xsdb.bat'
    if not xsdb.is_file() or not TCL.is_file():
        raise FileNotFoundError('XSDB or the read-only G6 diagnostic Tcl script is missing')
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    stdout_path = output_prefix.with_suffix('.stdout.log')
    stderr_path = output_prefix.with_suffix('.stderr.log')
    command = [str(xsdb), str(TCL), hex(address), str(size)]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                timeout=50, check=False)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ''
        stderr = exc.stderr or ''
        if isinstance(stdout, bytes):
            stdout = stdout.decode('utf-8', errors='replace')
        if isinstance(stderr, bytes):
            stderr = stderr.decode('utf-8', errors='replace')
        stdout_path.write_text(stdout, encoding='utf-8')
        stderr_path.write_text(stderr, encoding='utf-8')
        raise TimeoutError('Read-only G6 diagnostic snapshot exceeded 50 seconds') from exc
    stdout_path.write_text(result.stdout, encoding='utf-8')
    stderr_path.write_text(result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'XSDB diagnostic read failed with exit {result.returncode}')
    snapshot = parse_snapshot(result.stdout)
    record = {
        'schema': 'eyepqc-g6-rekey-diagnostic-v2',
        'captured_utc': datetime.now(timezone.utc).isoformat(),
        'build': identity,
        'address': address,
        'size': size,
        'diagnostic': snapshot,
        'evidence_scope': 'read-only AP0 DDR metadata; packet payloads and keys not read',
    }
    json_path = output_prefix.with_suffix('.json')
    json_path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--tool-root', type=Path, required=True)
    parser.add_argument('--output-prefix', type=Path, required=True)
    args = parser.parse_args()
    try:
        record = capture(args.workspace.resolve(), args.tool_root.resolve(),
                         args.output_prefix.resolve())
    except Exception as exc:
        print(f'G6_REKEY_DIAG_CAPTURE_FAIL {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1
    diag = record['diagnostic']
    print(f"G6_REKEY_DIAG_CAPTURE_OK phase={diag['phase']} "
          f"hello_attempts={diag['hello_attempts']} "
          f"ack_attempts={diag['hello_ack_send_attempts']} "
          f"ack_status={diag['hello_ack_send_status']} json={args.output_prefix.with_suffix('.json')}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
