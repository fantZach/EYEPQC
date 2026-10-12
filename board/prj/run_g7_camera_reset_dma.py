"""Run one controlled camera-reset/DMA-timeout G7 experiment; dry-run by default."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pc/src/host'))
from build_manifest import verify


def load_record(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def session_record(record):
    sessions = record.get('sessions')
    if not isinstance(sessions, list) or len(sessions) != 1 or not isinstance(sessions[0], dict):
        return None
    return sessions[0]


def verified_count(session):
    if not session:
        return 0
    return int(session.get('observed_verified_frames', 0))


def build_worker_command(python, workspace, seconds, no_jtag, tool_root):
    command = [str(python), str(ROOT / 'pc/src/host/g6_board.py'), '--workspace', str(workspace),
               '--tool-root', str(tool_root), '--seconds', str(seconds), '--sessions', '1',
               '--report-key-fingerprint']
    if no_jtag:
        command.append('--no-jtag')
    return command


def wait_stable_frame_count(read_count, timeout=8.0, quiet_period=1.0, poll_interval=0.2,
                            clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    last = read_count()
    last_change = clock()
    samples = [dict(offset_seconds=0.0, verified_frames=last)]
    while clock() < deadline:
        sleep(min(poll_interval, max(0.0, deadline - clock())))
        current = read_count()
        now = clock()
        samples.append(dict(offset_seconds=round(timeout - max(0.0, deadline - now), 3),
                            verified_frames=current))
        if current != last:
            last, last_change = current, now
        if now - last_change >= quiet_period:
            return last, samples
    raise TimeoutError(f'authenticated frame count did not stabilize: {samples}')


def run_worker(python, workspace, seconds, no_jtag, tool_root, output_dir, name, timeout):
    stdout_path, stderr_path = output_dir / f'{name}.stdout.log', output_dir / f'{name}.stderr.log'
    command = build_worker_command(python, workspace, seconds, no_jtag, tool_root)
    stdout = stdout_path.open('wb')
    stderr = stderr_path.open('wb')
    process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        result_path = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            text = stdout_path.read_text(encoding='utf-8', errors='replace')
            match = re.search(r'^G6_RUN_RESULT path=(.+)$', text, re.MULTILINE)
            if match:
                result_path = Path(match.group(1).strip())
                break
            if process.poll() is not None:
                raise RuntimeError(f'{name} receiver exited before publishing a result; see {stdout_path}')
            time.sleep(0.1)
        if result_path is None:
            raise TimeoutError(f'{name} receiver did not publish a result path')
        return process, result_path, stdout, stderr, stdout_path, stderr_path
    except Exception:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        stdout.close(); stderr.close()
        raise


def wait_frames(process, path, minimum, timeout, stdout_path, stderr_path):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            record = load_record(path)
            current = session_record(record)
            if verified_count(current) >= minimum:
                return record, current
            if record.get('status') == 'failed':
                raise RuntimeError(f'G6 receiver failed before baseline frames: {record.get("error")}')
        if process.poll() is not None:
            raise RuntimeError(f'G6 receiver exited before baseline frames; see {stdout_path} {stderr_path}')
        time.sleep(0.1)
    raise TimeoutError(f'G6 receiver did not decode {minimum} authenticated frames')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path,
                        default=ROOT / 'build/vitis/g6_camera_fault_20261008_ready')
    parser.add_argument('--tool-root', type=Path, default=Path('E:/fpg/2026.1'))
    parser.add_argument('--execute', action='store_true', help='allow temporary JTAG load and USB test')
    parser.add_argument('--first-seconds', type=int, default=30)
    parser.add_argument('--recovery-seconds', type=int, default=8)
    parser.add_argument('--wait-timeout', type=int, default=60)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    tool_root = args.tool_root.resolve()
    manifest, checked = verify(workspace, 'g6_usb_manifest.json')
    if manifest.get('variant') != 'controlled-camera-reset-real-dma-stall':
        raise RuntimeError('Refusing non-diagnostic G6 workspace')
    if args.first_seconds < 10 or args.recovery_seconds < 3 or args.wait_timeout < 15:
        parser.error('first session >=10s, recovery >=3s and wait timeout >=15s are required')
    python = ROOT / '.venv/Scripts/python.exe'
    xsdb = tool_root / 'Vivado/bin/xsdb.bat'
    nm = tool_root / 'gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-nm.exe'
    trigger = ROOT / 'board/prj/trigger_g6_camera_fault.tcl'
    if not python.is_file() or not xsdb.is_file() or not trigger.is_file():
        raise RuntimeError('Python, XSDB, or diagnostic trigger Tcl is missing')
    if not nm.is_file():
        raise RuntimeError('G6 board loader ARM nm tool is missing: ' + str(nm))
    owned = manifest['owned']
    for name in ('g6_camera_fault_inject', 'g6_camera_fault_diag', 'g6_ready', 'g6_status'):
        if name not in owned:
            raise RuntimeError('Diagnostic manifest missing owned symbol: ' + name)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '_' + uuid.uuid4().hex[:8]
    out = ROOT / 'report/g7_runs' / f'g7_camera_reset_dma_{run_id}'

    print(f'G7_CAMERA_DMA_PREFLIGHT_OK checked={checked} board_accessed=false')
    print(f'variant={workspace} xsa_sha256={manifest["xsa_sha256"]}')
    print('controlled trigger: PL cam_resetn/PWDN reset; no camera unplug, no SD/Flash write')
    print('evidence: S2MM busy/SR before and after 5ms timeout, bounded DMA reset, camera reconfiguration, JPEG recovery')
    if not args.execute:
        print('DRY_RUN_ONLY: add --execute only during the coordinated JTAG/USB-exclusive window')
        return 0

    from serial.tools import list_ports
    devices = [p.device for p in list_ports.comports() if p.vid == 0x03FD and p.pid == 0x7020]
    if len(devices) != 1:
        raise RuntimeError(f'Expected exactly one G6 CDC device before execution, found {devices}')
    out.mkdir(parents=True, exist_ok=False)
    (out / 'run_metadata.json').write_text(json.dumps({
        'started_utc': datetime.now(timezone.utc).isoformat(),
        'variant': manifest.get('variant'), 'workspace': str(workspace),
        'xsa_sha256': manifest['xsa_sha256'], 'cdc_before_load': devices,
        'jtag_loads': 1, 'reload_after_fault': False,
        'camera_fault': 'controlled PL OV5640 reset/PWDN; not a physical unplug or sensor damage',
        'minimum_authenticated_frames': 2,
    }, indent=2) + '\n', encoding='utf-8')

    worker = result_path = stdout = stderr = None
    try:
        worker, result_path, stdout, stderr, stdout_path, stderr_path = run_worker(
            python, workspace, args.first_seconds, False, tool_root, out,
            'before_fault_receiver', args.wait_timeout)
        before, before_session = wait_frames(worker, result_path, 2, args.wait_timeout, stdout_path, stderr_path)
        before_frames = verified_count(before_session)
        print(f'G7_CAMERA_DMA_BASELINE_READY frames={before_frames} result={result_path}', flush=True)

        trigger_command = [str(xsdb), str(trigger),
                           hex(owned['g6_camera_fault_inject']['address']),
                           hex(owned['g6_camera_fault_diag']['address']),
                           hex(owned['g6_ready']['address']), hex(owned['g6_status']['address']), '20000']
        triggered = subprocess.run(trigger_command, cwd=ROOT, capture_output=True, text=True, timeout=35)
        (out / 'trigger.stdout.log').write_text(triggered.stdout, encoding='utf-8')
        (out / 'trigger.stderr.log').write_text(triggered.stderr, encoding='utf-8')
        if triggered.returncode or 'G6_CAMERA_FAULT_DIAG_OK' not in triggered.stdout:
            raise RuntimeError('JTAG diagnostic trigger failed; see trigger.stdout.log and trigger.stderr.log')
        print(triggered.stdout.strip(), flush=True)

        def read_live_count():
            current_record = load_record(result_path)
            current_session = session_record(current_record)
            if current_record.get('status') == 'failed':
                raise RuntimeError(f'Old G6 receiver failed after diagnostic: {current_record.get("error")}')
            return verified_count(current_session)

        stable_frames, drain_samples = wait_stable_frame_count(read_live_count)
        if stable_frames < before_frames:
            raise RuntimeError('Authenticated frame count moved backwards after the diagnostic')
        try:
            worker.wait(timeout=args.first_seconds + args.wait_timeout)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError('Original receiver did not close normally after its bounded session') from exc
        stdout.close(); stderr.close()
        stdout = stderr = None
        final_before = load_record(result_path)
        old = session_record(final_before)
        if final_before.get('status') != 'passed' or verified_count(old) != stable_frames:
            raise RuntimeError('Old session did not finish at the stable post-fault frame count')

        recovery_stdout_path = out / 'recovery_receiver.stdout.log'
        recovery_stderr_path = out / 'recovery_receiver.stderr.log'
        recovery_stdout = recovery_stdout_path.open('wb')
        recovery_stderr = recovery_stderr_path.open('wb')
        recovery = subprocess.Popen(build_worker_command(
            python, workspace, args.recovery_seconds, True, tool_root), cwd=ROOT,
            stdout=recovery_stdout, stderr=recovery_stderr,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            try:
                recovery.wait(timeout=args.recovery_seconds + args.wait_timeout)
            except subprocess.TimeoutExpired:
                recovery.terminate()
                try:
                    recovery.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    recovery.kill()
                    recovery.wait(timeout=5)
                raise TimeoutError('Recovery receiver timed out and its owned process was stopped')
        finally:
            recovery_stdout.close()
            recovery_stderr.close()
        recovery_text = recovery_stdout_path.read_text(encoding='utf-8', errors='replace')
        if recovery.returncode:
            raise RuntimeError('New G6 receiver did not recover; see recovery_receiver logs')
        match = re.search(r'^G6_RUN_RESULT path=(.+)$', recovery_text, re.MULTILINE)
        if not match:
            raise RuntimeError('Recovery receiver did not publish a result path')
        new_path = Path(match.group(1).strip())
        recovered = load_record(new_path)
        new = session_record(recovered)
        if recovered.get('status') != 'passed' or verified_count(new) < 2:
            raise RuntimeError('Recovery did not authenticate/decode at least two new-session frames')
        if old.get('session_id') == new.get('session_id') or \
                old.get('video_key_sha256') == new.get('video_key_sha256'):
            raise RuntimeError('Recovery reused the old G6 session ID or video-key fingerprint')
        summary = {
            'status': 'passed', 'variant': manifest.get('variant'),
            'started_utc': datetime.now(timezone.utc).isoformat(),
            'workspace': str(workspace), 'manifest_xsa_sha256': manifest['xsa_sha256'],
            'baseline_g6_jtag_loads': 1, 'jtag_reload_after_fault': False,
            'camera_fault_scope': 'controlled PL camera reset/PWDN only; not physical unplug or sensor damage',
            'diagnostic_log': 'trigger.stdout.log',
            'before_fault': {'result_path': str(result_path), 'session_id': old['session_id'],
                             'video_key_sha256': old['video_key_sha256'],
                             'verified_frames': verified_count(old),
                             'frames_before_fault': before_frames,
                             'post_fault_frame_count_stability_samples': drain_samples,
                             'frames_after_fault_completion': stable_frames},
            'dma_observation': 'See trigger stdout: S2MM busy and status observed while PL camera stream reset; bounded timeout/reset/reconfigure completed.',
            'after_recovery': {'result_path': str(new_path), 'session_id': new['session_id'],
                               'video_key_sha256': new['video_key_sha256'],
                               'verified_frames': verified_count(new), 'fps': new.get('fps')},
            'board_dma_counters': None,
        }
        (out / 'batch_summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
        print(f'G7_CAMERA_DMA_RECOVERY_OK old={old["session_id"]} new={new["session_id"]} '
              f'frames={verified_count(old)}->{verified_count(new)} evidence={out}', flush=True)
        return 0
    except Exception as exc:
        (out / 'failure.txt').write_text(f'{type(exc).__name__}: {exc}\n', encoding='utf-8')
        print(f'G7_CAMERA_DMA_FAILED evidence={out} error={type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        raise
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
        if stdout is not None:
            stdout.close()
        if stderr is not None:
            stderr.close()


if __name__ == '__main__':
    raise SystemExit(main())
