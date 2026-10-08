"""Export integrity-checked authenticated recordings to MP4 or AVI."""
import math
from io import BytesIO
import os
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, UnidentifiedImageError

from demo_recording import recording_frames


class ExportCancelled(Exception):
    """Raised when a caller cancels an in-progress export."""


def _concat_quote(path):
    # ffmpeg concat files use shell-like single quoting, but are not shell input.
    return "'" + str(path).replace("\\", "/").replace("'", "'\\''") + "'"


def _validated_count(folder, cancel_event, progress=None):
    count = 0
    dimensions = None
    previous = None
    for row, jpeg in recording_frames(folder):
        if cancel_event and cancel_event.is_set():
            raise ExportCancelled('导出已取消')
        elapsed = row['elapsed']
        if not math.isfinite(elapsed) or elapsed < 0 or (previous is not None and elapsed < previous):
            raise ValueError('录像时间戳无效')
        try:
            with Image.open(BytesIO(jpeg)) as image:
                image.load()
                if image.format != 'JPEG' or image.width < 1 or image.height < 1:
                    raise ValueError('录像帧不是有效 JPEG')
                if dimensions is None:
                    dimensions = image.size
                elif dimensions != image.size:
                    raise ValueError('录像帧尺寸不一致')
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError('录像帧不是有效 JPEG') from exc
        previous = elapsed
        count += 1
        if progress and (count == 1 or count % 25 == 0):
            progress('校验录像', count, None)
    if not count:
        raise ValueError('录像没有可导出的认证帧')
    return count


def export_recording(folder, target, container, cancel_event=None, progress=None):
    """Write MP4 (H.264) or AVI (MJPEG), preserving frame elapsed timestamps.

    Frames are hash-checked and decoded in a first streaming pass. A second pass
    copies one frame at a time into a private temporary directory for ffmpeg.
    The destination is only replaced after the encoded file decodes successfully.
    """
    folder, target = Path(folder), Path(target)
    container = container.lower()
    if container not in ('mp4', 'avi') or target.suffix.lower() != '.' + container:
        raise ValueError('导出格式与目标扩展名不匹配')
    if target.exists():
        raise FileExistsError(f'目标文件已存在：{target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    if cancel_event and cancel_event.is_set():
        raise ExportCancelled('导出已取消')
    count = _validated_count(folder, cancel_event, progress)

    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError('缺少 imageio-ffmpeg，请按 requirements.txt 安装演示依赖') from exc
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    temp_output = None
    try:
        with tempfile.TemporaryDirectory(prefix='eyepqc-export-') as work:
            work = Path(work)
            concat = work / 'frames.ffconcat'
            frame_dir = work / 'frames'
            frame_dir.mkdir()
            timings = []
            for index, (row, jpeg) in enumerate(recording_frames(folder)):
                if cancel_event and cancel_event.is_set():
                    raise ExportCancelled('导出已取消')
                frame = frame_dir / f'{index:08d}.jpg'
                frame.write_bytes(jpeg)
                timings.append(row['elapsed'])
                if progress and (index == 0 or (index + 1) % 25 == 0):
                    progress('准备编码帧', index + 1, count)
            if len(timings) != count:
                raise ValueError('录像帧数在导出期间发生变化')
            # Rewrite the manifest with per-frame durations. VFR timestamps keep
            # the recorded elapsed-time gaps instead of imposing a fixed frame rate.
            with concat.open('w', encoding='utf-8', newline='\n') as listing:
                listing.write('ffconcat version 1.0\n')
                fallback = 1 / 30
                for index, elapsed in enumerate(timings):
                    frame = frame_dir / f'{index:08d}.jpg'
                    listing.write('file ' + _concat_quote(frame) + '\n')
                    listing.write('option framerate 1000\n')
                    duration = (timings[index + 1] - elapsed) if index + 1 < count else fallback
                    listing.write(f'duration {max(duration, 1e-6):.9f}\n')

            descriptor, temporary = tempfile.mkstemp(prefix='.' + target.stem + '-',
                                                       suffix='.tmp.' + container,
                                                       dir=target.parent)
            os.close(descriptor)
            temp_output = Path(temporary)
            codec = ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart'] if container == 'mp4' else ['-c:v', 'mjpeg', '-q:v', '2']
            command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-safe', '0',
                       '-f', 'concat', '-i', str(concat), '-fps_mode', 'vfr', *codec,
                       '-f', 'mp4' if container == 'mp4' else 'avi', str(temp_output)]
            if progress:
                progress('编码视频', count, count)
            _run(command, cancel_event, work / 'encode.log')
            # Decode the complete result before publishing it.
            decode_log = work / 'decode.framemd5'
            _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(temp_output),
                  '-fps_mode', 'passthrough', '-f', 'framemd5', '-'], cancel_event,
                 work / 'decode.err', stdout_path=decode_log)
            decoded = sum(1 for line in decode_log.read_text(encoding='utf-8', errors='replace').splitlines()
                          if line and not line.startswith('#'))
            if decoded != count:
                raise RuntimeError(f'导出解码帧数不匹配：期望 {count}，实际 {decoded}')
            if cancel_event and cancel_event.is_set():
                raise ExportCancelled('导出已取消')
            if not temp_output.is_file() or temp_output.stat().st_size == 0:
                raise RuntimeError('ffmpeg 未生成有效导出文件')
            os.link(temp_output, target)
            temp_output.unlink()
            temp_output = None
            if progress:
                progress('完成', count, count)
        return target
    finally:
        if temp_output is not None:
            try:
                temp_output.unlink()
            except FileNotFoundError:
                pass


def _run(command, cancel_event, log_path, stdout_path=None):
    with Path(log_path).open('wb') as log:
        stdout = Path(stdout_path).open('wb') if stdout_path else subprocess.DEVNULL
        try:
            process = subprocess.Popen(command, stdout=stdout, stderr=log)
        finally:
            if stdout_path:
                stdout.close()
    try:
        while True:
            if cancel_event and cancel_event.is_set():
                raise ExportCancelled('导出已取消')
            try:
                returncode = process.wait(timeout=.1)
                break
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise
    if returncode:
        detail = Path(log_path).read_text(encoding='utf-8', errors='replace').strip()
        raise RuntimeError(detail or f'ffmpeg 失败，退出码 {returncode}')
