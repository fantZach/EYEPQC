"""Streaming authenticated JPEG recording, with timing and checked replay.

Recordings contain decrypted images. Hashes detect accidental file changes;
they are not a substitute for the live GCM/Finished verification.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


class FrameRecording:
    def __init__(self, folder, source):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=False)
        self.index = (self.folder / 'frames.jsonl').open('w', encoding='utf-8')
        self.started = time.monotonic()
        self._last_elapsed = -1.0
        self._session_id = None
        self._camera_origin = None
        self._elapsed_origin = None
        self._last_camera_timestamp = None
        self.closed = False
        self.summary = dict(format='eyepqc-jpeg-v1', status='recording', frames=0,
                            source=source, plaintext=True,
                            generated_utc=datetime.now(timezone.utc).isoformat(),
                            timebase='protocol timestamp in microseconds, with host-monotonic session anchors',
                            integrity='sha256 for replay consistency; not a signature or renewed GCM verification')
        self._save()

    def _save(self):
        temporary = self.folder / 'recording.json.tmp'
        temporary.write_text(json.dumps(self.summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(self.folder / 'recording.json')

    def write(self, jpeg, header):
        if self.closed:
            raise RuntimeError('recording is closed')
        number = self.summary['frames']
        name = f'{number:08d}.jpg'
        # The caller must have completed GCM, replay, assembly and JPEG checks.
        host_elapsed = time.monotonic() - self.started
        if header.session_id != self._session_id:
            # Timestamp origin is session-local; anchor a new epoch to host arrival.
            self._session_id = header.session_id
            self._camera_origin = header.timestamp
            self._elapsed_origin = max(host_elapsed, self._last_elapsed + 1e-6)
        elif header.timestamp <= self._last_camera_timestamp:
            raise ValueError('camera timestamp must increase within a session')
        elapsed = self._elapsed_origin + (header.timestamp - self._camera_origin) / 1_000_000
        if elapsed <= self._last_elapsed:
            raise ValueError('recording elapsed time must increase')
        (self.folder / name).write_bytes(jpeg)
        row = dict(file=name, elapsed=elapsed,
                   session_id=header.session_id, frame_id=header.frame_id,
                   camera_timestamp=header.timestamp, sha256=hashlib.sha256(jpeg).hexdigest())
        self.index.write(json.dumps(row) + '\n')
        self.index.flush()
        self._last_elapsed = elapsed
        self._last_camera_timestamp = header.timestamp
        self.summary['frames'] += 1

    def close(self):
        if not self.closed:
            self.index.close()
            self.closed = True
            self.summary.update(status='closed', seconds=time.monotonic() - self.started)
            self._save()


def recording_frames(folder):
    """Read sequentially and verify each file before returning its plaintext."""
    folder = Path(folder)
    summary = json.loads((folder / 'recording.json').read_text(encoding='utf-8'))
    if summary.get('format') != 'eyepqc-jpeg-v1' or summary.get('status') != 'closed':
        raise ValueError('recording is incomplete or unsupported')
    previous = 0.0
    previous_session = None
    previous_camera_timestamp = None
    count = 0
    with (folder / 'frames.jsonl').open(encoding='utf-8') as index:
        for number, line in enumerate(index):
            row = json.loads(line)
            if (row['file'] != f'{number:08d}.jpg' or
                    not isinstance(row['elapsed'], (int, float)) or
                    not isinstance(row.get('session_id'), int) or
                    not isinstance(row.get('camera_timestamp'), int)):
                raise ValueError('invalid recording frame index')
            if not previous <= row['elapsed'] < float('inf'):
                raise ValueError('invalid recording timing')
            if (row['session_id'] == previous_session and
                    row['camera_timestamp'] <= previous_camera_timestamp):
                raise ValueError('camera timestamp must increase within a session')
            path = folder / row['file']
            if path.is_symlink():
                raise ValueError('recording frame must not be a symbolic link')
            jpeg = path.read_bytes()
            if hashlib.sha256(jpeg).hexdigest() != row['sha256']:
                raise ValueError('recording frame hash mismatch')
            previous = row['elapsed']
            previous_session = row['session_id']
            previous_camera_timestamp = row['camera_timestamp']
            count += 1
            yield row, jpeg
    if count != summary['frames']:
        raise ValueError('recording frame count mismatch')
