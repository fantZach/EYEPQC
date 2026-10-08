"""Run one isolated 20-trial G7 camera-reset or DMA-routing-stall recovery batch."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/host'))
from build_manifest import verify

TRIGGER_NAMES = {'camera-reset': 1, 'routing-stall': 2}


def worker_command(python, workspace, tool_root, seconds, no_jtag):
    command = [str(python), str(ROOT / 'src/host/g6_board.py'), '--workspace', str(workspace),
               '--tool-root', str(tool_root), '--seconds', str(seconds), '--sessions', '1',
               '--report-key-fingerprint', '--drain-stop', '--bounded-control-write',
               '--debug-stage']
    if no_jtag:
        command.append('--no-jtag')
    return command


def session_record(record):
    sessions = record.get('sessions')
    return sessions[0] if isinstance(sessions, list) and len(sessions) == 1 else None


def get_frames(session):
    return int((session or {}).get('observed_verified_frames', 0))


def read_live_record(path, timeout=2.0):
    """Retry only transient Windows sharing/half-write reads within a fixed bound."""
    deadline = time.monotonic() + timeout
    last_error = None
    while True:
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (PermissionError, json.JSONDecodeError) as exc:
            last_error = exc
            if time.monotonic() >= deadline:
                raise last_error
            time.sleep(0.02)


def parse_trigger(stdout):
    diag = re.search(r'^G6_AUTO_RECOVERY_DIAG (.+)$', stdout, re.MULTILINE)
    counters = re.search(r'^G6_AUTO_COUNTERS (.+)$', stdout, re.MULTILINE)
    transport = re.search(r'^G6_AUTO_TRANSPORT_FAILURE (.+)$', stdout, re.MULTILINE)
    if not diag or not counters or not transport:
        raise ValueError('XSDB did not emit complete recovery/counter telemetry')
    values = {}
    for field in diag.group(1).split():
        key, value = field.split('=', 1)
        values[key] = int(value, 16) if key in {'magic', 'sr', 'camera_status'} else int(value)
    for field in counters.group(1).split():
        key, value = field.split('=', 1)
        before, after = value.split('->', 1)
        values[f'{key}_before'] = int(before)
        values[f'{key}_after'] = int(after)
    for field in transport.group(1).split():
        key, value = field.split('=', 1)
        values[key] = int(value)
    return values


def validate_trigger(values, mode):
    if values.get('magic') != 0x47415231 or values.get('state') != 2 or \
            values.get('stage') != 5 or values.get('mode') != mode:
        raise ValueError('Candidate recovery did not finish in the expected state/mode')
    if values.get('observation') != 3 or values.get('busy_start') != 1 or \
            values.get('busy_deadline') != 1 or values.get('elapsed_us', 0) < 3_000_000:
        raise ValueError('Real S2MM Busy deadline was not observed for 3 seconds')
    if values.get('sr', 0) & 0x4000:
        raise ValueError('DMA IRQ error was observed; this trial is not a clean Busy-timeout pass')
    if values.get('recovery_status') != 0 or \
            (values.get('camera_status', 0) & 0x0080ffff) != 0x00805640:
        raise ValueError('Bounded DMA reset or camera reconfiguration failed')
    if values.get('capture_after') != values.get('capture_before', -2) + 1 or \
            values.get('dropped_after') != values.get('dropped_before', -2) + 1 or \
            values.get('fatal_after') != values.get('fatal_before', -2):
        raise ValueError('Firmware capture/drop/fatal counter deltas do not match one recovery')
    if values.get('control_after') != values.get('control_before') or \
            values.get('transport_after') != values.get('transport_before') or \
            values.get('status_before') != 1 or values.get('status_after') != 1:
        raise ValueError('Firmware health counters changed across recovery')
    if values.get('send_status') != 0 or values.get('resume_status') != 0 or \
            values.get('transport_error_count') != 0:
        raise ValueError('Transport-failure snapshot is nonzero during successful recovery')


def stop_owned_worker(process, stdout, stderr, grace=5):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=grace)
    for stream in (stdout, stderr):
        if stream is not None and not stream.closed:
            stream.close()


def launch_worker(python, workspace, tool_root, seconds, no_jtag, out, name):
    stdout_path, stderr_path = out / f'{name}.stdout.log', out / f'{name}.stderr.log'
    stdout, stderr = stdout_path.open('wb'), stderr_path.open('wb')
    command = worker_command(python, workspace, tool_root, seconds, no_jtag)
    process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        deadline = time.monotonic() + 30
        record_path = None
        while time.monotonic() < deadline:
            text = stdout_path.read_text(encoding='utf-8', errors='replace')
            match = re.search(r'^G6_RUN_RESULT path=(.+)$', text, re.MULTILINE)
            if match:
                record_path = Path(match.group(1).strip())
                break
            if process.poll() is not None:
                raise RuntimeError(f'{name} exited before publishing its result path')
            time.sleep(0.1)
        if record_path is None:
            raise TimeoutError(f'{name} did not publish a result path')
        return process, record_path, stdout, stderr, stdout_path, stderr_path
    except Exception:
        stop_owned_worker(process, stdout, stderr)
        raise


def wait_for_frames(process, record_path, minimum=2, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if record_path.is_file():
            record = read_live_record(record_path)
            session = session_record(record)
            if get_frames(session) >= minimum:
                return record, session
            if record.get('status') == 'failed':
                raise RuntimeError(f'G6 receiver failed before video: {record.get("error")}')
        if process.poll() is not None:
            raise RuntimeError('G6 receiver exited before two authenticated frames')
        time.sleep(0.1)
    raise TimeoutError('G6 receiver did not produce two authenticated/decoded frames')


def verify_fault_worker_before_trigger(process, record_path, expected_session, expected_key,
                                       minimum_frames):
    if process.poll() is not None:
        raise RuntimeError('Fault-side receiver exited before trigger')
    record = read_live_record(record_path)
    if record.get('status') != 'running':
        raise RuntimeError(f'Fault-side receiver is not healthy before trigger: {record.get("status")}')
    session = session_record(record)
    if not session or session.get('session_id') != expected_session or \
            session.get('video_key_sha256') != expected_key or get_frames(session) < minimum_frames:
        raise RuntimeError('Fault-side session/frame evidence changed or regressed before trigger')
    return record, session


def verify_external_sources(manifest, tool_root):
    tool_root = Path(tool_root).resolve()
    entries = manifest.get('external_sources', {})
    if manifest.get('external_sources_root') != 'tool-root' or not entries:
        raise ValueError('Candidate manifest must pin tool-root-relative external sources')
    checked = 0
    for relative, expected in entries.items():
        path = (tool_root / relative).resolve()
        if not path.is_relative_to(tool_root) or not path.is_file():
            raise ValueError('Missing or invalid external manifest file: ' + relative)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('External tool source changed; rebuild before board use: ' + relative)
        checked += 1
    return checked


def read_post_stop_health(xsdb, trigger, owned, trial_dir):
    args = [str(xsdb), str(trigger),
            hex(owned['g6_status']['address']), hex(owned['g6_fatal_errors']['address']),
            hex(owned['g6_control_errors']['address']), hex(owned['g6_transport_errors']['address']),
            hex(owned['g6_ready']['address']), hex(owned['g6_transport_failure_diag']['address'])]
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=45)
    (trial_dir / 'post_stop_health.stdout.log').write_text(result.stdout, encoding='utf-8')
    (trial_dir / 'post_stop_health.stderr.log').write_text(result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Read-only post-STOP health snapshot failed; see raw XSDB logs')
    match = re.search(r'^G6_AUTO_HEALTH (.+)$', result.stdout, re.MULTILINE)
    if not match:
        raise RuntimeError('XSDB did not emit post-STOP health counters')
    values = {}
    for field in match.group(1).split():
        key, value = field.split('=', 1)
        values[key] = int(value, 16) if key == 'ready' else int(value)
    transport = re.search(r'^G6_AUTO_TRANSPORT_FAILURE (.+)$', result.stdout, re.MULTILINE)
    if not transport:
        raise RuntimeError('XSDB did not emit post-STOP transport snapshot')
    for field in transport.group(1).split():
        key, value = field.split('=', 1)
        values[key] = int(value)
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path,
                        default=ROOT / 'build/vitis/g6_auto_recovery_20261008_candidate4')
    parser.add_argument('--tool-root', type=Path, default=Path('E:/fpg/2026.1'))
    parser.add_argument('--mode', choices=TRIGGER_NAMES, required=True,
                        help='run a separate camera-reset or routing-stall batch')
    parser.add_argument('--attempts', type=int, default=20)
    parser.add_argument('--execute', action='store_true', help='use JTAG and USB hardware')
    parser.add_argument('--first-seconds', type=int, default=60,
                        help='fault-side host receiver lifetime; stopped by the harness after recovery')
    parser.add_argument('--recovery-seconds', type=int, default=2,
                        help='new-session authenticated video duration after each fault')
    parser.add_argument('--wait-timeout', type=int, default=45)
    args = parser.parse_args()
    workspace, tools = args.workspace.resolve(), args.tool_root.resolve()
    manifest, checked = verify(workspace, 'g6_usb_manifest.json')
    if manifest.get('variant') != 'g6-auto-camera-dma-recovery-usb-bounded-candidate-v3':
        raise RuntimeError('Refusing a non-auto-recovery candidate workspace')
    external_checked = verify_external_sources(manifest, tools)
    if not 1 <= args.attempts <= 20 or args.first_seconds < 10 or \
            args.recovery_seconds < 2 or args.wait_timeout < 15:
        parser.error('attempts 1..20, first session >=10s, recovery >=2s, timeout >=15s required')
    python = ROOT / '.venv/Scripts/python.exe'
    xsdb = tools / 'Vivado/bin/xsdb.bat'
    nm = tools / 'gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-nm.exe'
    trigger = ROOT / 'prj/trigger_g6_auto_recovery.tcl'
    if not python.is_file() or not xsdb.is_file() or not nm.is_file() or not trigger.is_file():
        raise RuntimeError('Python, XSDB, ARM nm, or auto-recovery trigger is missing')
    owned_names = ('g6_auto_recovery_request', 'g6_auto_recovery_diag', 'g6_ready',
                   'g6_status', 'g6_capture_errors', 'g6_dropped', 'g6_fatal_errors',
                   'g6_control_errors', 'g6_transport_errors', 'g6_transport_failure_diag')
    owned = manifest.get('owned', {})
    if any(name not in owned for name in owned_names):
        raise RuntimeError('Candidate manifest is missing auto-recovery/telemetry symbols')

    print(f'G7_AUTO_RECOVERY_PREFLIGHT_OK hashes={checked} external_hashes={external_checked} board_accessed=false')
    print(f'mode={args.mode} attempts={args.attempts} variant={workspace}')
    print(f'expected: authenticated frames before each {args.mode} fault; actual 3s Busy; bounded reset/configure; fresh key/session; >=2s recovered video; JTAG load once, no reload within batch')
    if not args.execute:
        print('DRY_RUN_ONLY: board was not accessed; add --execute only during a coordinated USB/JTAG window')
        return 0

    from serial.tools import list_ports
    cdc = [p.device for p in list_ports.comports() if p.vid == 0x03FD and p.pid == 0x7020]
    if len(cdc) != 1:
        raise RuntimeError(f'Expected one G6 CDC device for the existing baseline, found {cdc}')
    out = ROOT / 'report/g7_runs' / (
        f'g7_auto_recovery_{args.mode}_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")}_'
        f'{uuid.uuid4().hex[:8]}')
    out.mkdir(parents=True, exist_ok=False)
    summary = {'status': 'running', 'mode': args.mode, 'mode_id': TRIGGER_NAMES[args.mode],
               'attempts_requested': args.attempts, 'trials': [], 'workspace': str(workspace),
               'variant': manifest['variant'], 'xsa_sha256': manifest['xsa_sha256'],
               'jtag_loads': 0, 'jtag_reloads_between_trials': False,
               'old_usbfix3_source_modified': False, 'board_counters_scope':
               'g6_capture_errors/g6_dropped/g6_fatal_errors owned ELF counters only'}
    summary_path = out / 'batch_summary.json'
    summary_path.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    mode = TRIGGER_NAMES[args.mode]
    worker = recovery_worker = None
    stdout = stderr = recovery_stdout = recovery_stderr = None
    jtag_loaded = False
    try:
        for index in range(1, args.attempts + 1):
            trial_dir = out / f'trial_{index:02d}'
            trial_dir.mkdir()
            trial = {'trial': index, 'mode': args.mode, 'mode_id': mode,
                     'jtag_load_before': not jtag_loaded,
                     'jtag_reload_after_initial_load': False}
            (trial_dir / 'trial.json').write_text(json.dumps(trial, indent=2) + '\n', encoding='utf-8')
            worker, old_path, stdout, stderr, stdout_path, stderr_path = launch_worker(
                python, workspace, tools, args.first_seconds, jtag_loaded, trial_dir,
                'fault_side_receiver')
            jtag_loaded = True
            if index == 1:
                summary['jtag_loads'] = 1
            before_record, old = wait_for_frames(worker, old_path, 2, args.wait_timeout)
            if worker.poll() is not None:
                raise RuntimeError('Fault-side receiver must still be alive before trigger')
            old_sid, old_fp, old_frames = (old.get('session_id'), old.get('video_key_sha256'),
                                            get_frames(old))
            if not old_sid or not old_fp or old_frames < 2:
                raise RuntimeError('Fault-side session lacks authenticated frame/session/key evidence')
            build = before_record.get('build', {})
            if build.get('xsa_sha256') != manifest.get('xsa_sha256') or \
                    build.get('elf_sha256') != manifest.get('artifacts', {}).get('g6_usb/build/g6_usb.elf'):
                raise RuntimeError('Fault-side receiver build identity differs from verified candidate manifest')
            trial.update({'fault_receiver_result': str(old_path),
                          'old_session_id': old_sid, 'old_video_key_sha256': old_fp,
                          'verified_frames_before_fault': old_frames,
                          'fault_receiver_live_before_trigger': True,
                          'build': before_record.get('build')})
            (trial_dir / 'trial.json').write_text(json.dumps(trial, indent=2) + '\n', encoding='utf-8')

            before_record, old = verify_fault_worker_before_trigger(
                worker, old_path, old_sid, old_fp, old_frames)
            trial['pre_trigger_health'] = {
                'status': before_record.get('status'),
                'session_id': old.get('session_id'),
                'video_key_sha256': old.get('video_key_sha256'),
                'verified_frames': get_frames(old),
                'worker_live': worker.poll() is None,
            }
            (trial_dir / 'trial.json').write_text(json.dumps(trial, indent=2) + '\n', encoding='utf-8')

            trigger_args = [str(xsdb), str(trigger),
                hex(owned['g6_auto_recovery_request']['address']),
                hex(owned['g6_auto_recovery_diag']['address']),
                hex(owned['g6_ready']['address']), hex(owned['g6_status']['address']),
                str(mode), '15000', hex(owned['g6_capture_errors']['address']),
                hex(owned['g6_dropped']['address']), hex(owned['g6_fatal_errors']['address']),
                hex(owned['g6_control_errors']['address']),
                hex(owned['g6_transport_errors']['address']),
                hex(owned['g6_transport_failure_diag']['address'])]
            trigger_result = subprocess.run(trigger_args, cwd=ROOT, capture_output=True,
                                            text=True, timeout=45)
            (trial_dir / 'trigger.stdout.log').write_text(trigger_result.stdout, encoding='utf-8')
            (trial_dir / 'trigger.stderr.log').write_text(trigger_result.stderr, encoding='utf-8')
            if trigger_result.returncode or 'G6_AUTO_RECOVERY_OK' not in trigger_result.stdout:
                raise RuntimeError(f'Trial {index} trigger failed; see raw XSDB logs')
            telemetry = parse_trigger(trigger_result.stdout)
            validate_trigger(telemetry, mode)
            trial['board_telemetry'] = telemetry
            trial['trigger_stdout'] = 'trigger.stdout.log'

            # Stop only the owned host receiver after firmware has completed the recovery
            # and committed its counters; then immediately release/reopen CDC for a fresh HELLO.
            time.sleep(0.3)
            stop_owned_worker(worker, stdout, stderr)
            worker = stdout = stderr = None
            if not old_path.is_file():
                raise RuntimeError('Fault-side receiver result disappeared after stop')
            old_final = read_live_record(old_path)
            old_final_session = session_record(old_final)
            if not old_final_session or old_final_session.get('session_id') != old_sid or \
                    old_final_session.get('video_key_sha256') != old_fp or \
                    get_frames(old_final_session) < 2:
                raise RuntimeError('Fault-side host evidence changed or lost authenticated frames')
            trial['fault_receiver_harness_stop_after_recovery'] = True
            trial['fault_receiver_record_status_after_stop'] = old_final.get('status')
            trial['fault_receiver_stop_reason'] = (
                'Harness stops its own still-live receiver after firmware recovery telemetry '
                'to release CDC for a new process HELLO; this is not counted as a receiver-exit trial.')

            recovery_worker, new_path, recovery_stdout, recovery_stderr, new_stdout_path, new_stderr_path = \
                launch_worker(python, workspace, tools, args.recovery_seconds, True, trial_dir,
                              'recovery_receiver')
            try:
                recovery_worker.wait(timeout=args.recovery_seconds + args.wait_timeout)
            except subprocess.TimeoutExpired:
                raise TimeoutError(f'Trial {index} recovery receiver timed out')
            recovery_stdout.close(); recovery_stderr.close()
            recovery_stdout = recovery_stderr = None
            if recovery_worker.returncode:
                raise RuntimeError(f'Trial {index} fresh session failed; see recovery receiver logs')
            new_record = read_live_record(new_path)
            new = session_record(new_record)
            if new_record.get('status') != 'passed' or get_frames(new) < 2 or \
                    float(new.get('seconds', 0)) < 1.8:
                raise RuntimeError(f'Trial {index} did not recover >=2s authenticated video')
            new_build = new_record.get('build', {})
            if new_build.get('xsa_sha256') != manifest.get('xsa_sha256') or \
                    new_build.get('elf_sha256') != manifest.get('artifacts', {}).get('g6_usb/build/g6_usb.elf'):
                raise RuntimeError(f'Trial {index} recovery receiver used a different build')
            if new.get('session_id') == old_sid or new.get('video_key_sha256') == old_fp:
                raise RuntimeError(f'Trial {index} reused old session ID or key fingerprint')
            post_stop = read_post_stop_health(xsdb, ROOT / 'prj/read_g6_auto_health.tcl',
                                              owned, trial_dir)
            if post_stop.get('status') != 1 or post_stop.get('ready') != 0x36475345 or \
                    post_stop.get('fatal') != telemetry.get('fatal_after') or \
                    post_stop.get('control') != telemetry.get('control_after') or \
                    post_stop.get('transport') != telemetry.get('transport_after'):
                raise RuntimeError(f'Trial {index} health counters changed during STOP/DTR close')
            trial.update({'recovery_receiver_result': str(new_path),
                          'new_session_id': new.get('session_id'),
                          'new_video_key_sha256': new.get('video_key_sha256'),
                          'verified_recovery_frames': get_frames(new),
                          'recovery_seconds': new.get('seconds'), 'recovery_fps': new.get('fps'),
                          'fresh_hello': True, 'jtag_reload_for_recovery': False,
                          'post_stop_health': post_stop,
                          'status': 'passed'})
            (trial_dir / 'trial.json').write_text(json.dumps(trial, indent=2) + '\n', encoding='utf-8')
            summary['trials'].append({'trial': index, 'status': 'passed',
                                      'old_session_id': old_sid, 'new_session_id': new['session_id'],
                                      'old_key_sha256': old_fp,
                                      'new_key_sha256': new['video_key_sha256'],
                                      'elapsed_us': telemetry['elapsed_us'],
                                      'frames_before_fault': old_frames,
                                      'frames_after_recovery': get_frames(new)})
            summary_path.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
            recovery_worker = None
            print(f'G7_AUTO_RECOVERY_TRIAL_PASS {index}/{args.attempts} mode={args.mode} '
                  f'elapsed_us={telemetry["elapsed_us"]} frames={old_frames}->{get_frames(new)} '
                  f'session={old_sid}->{new["session_id"]}', flush=True)

        summary['status'] = 'passed'
        summary['completed_utc'] = datetime.now(timezone.utc).isoformat()
        summary_path.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
        print(f'G7_AUTO_RECOVERY_BATCH_PASS mode={args.mode} trials={len(summary["trials"])} '
              f'evidence={out}', flush=True)
        return 0
    except Exception as exc:
        summary['status'] = 'failed'
        summary['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        summary['failed_utc'] = datetime.now(timezone.utc).isoformat()
        summary_path.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
        (out / 'failure.txt').write_text(f'{type(exc).__name__}: {exc}\n', encoding='utf-8')
        print(f'G7_AUTO_RECOVERY_BATCH_FAILED evidence={out} error={type(exc).__name__}: {exc}',
              file=sys.stderr, flush=True)
        raise
    finally:
        stop_owned_worker(worker, stdout, stderr)
        stop_owned_worker(recovery_worker, recovery_stdout, recovery_stderr)


if __name__ == '__main__':
    main()
