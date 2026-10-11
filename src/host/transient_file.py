"""Best-effort transient files for host-to-board test exchanges.

These helpers reduce accidental retention of test secrets. They do not provide
secure deletion guarantees on SSDs, journaled filesystems, or copy-on-write
storage.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import tempfile


def read_mutable_file(path, max_size=16 * 1024 * 1024):
    """Read a bounded regular file directly into a wipeable bytearray."""
    path = Path(path)
    data = bytearray()
    try:
        with path.open("rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("sensitive input must be a regular file")
            size = metadata.st_size
            if size > max_size:
                raise ValueError("sensitive input exceeds size limit")
            data = bytearray(size)
            view = memoryview(data)
            offset = 0
            try:
                while offset < size:
                    count = stream.readinto(view[offset:])
                    if not count:
                        raise OSError("sensitive input changed while being read")
                    offset += count
            finally:
                view.release()
            if os.fstat(stream.fileno()).st_size != size:
                raise OSError("sensitive input changed while being read")
        return data
    except BaseException:
        data[:] = bytes(len(data))
        raise


def _wipe_and_unlink(path):
    path = Path(path)
    try:
        with path.open("r+b") as stream:
            remaining = os.fstat(stream.fileno()).st_size
            zeros = bytes(min(4096, remaining))
            while remaining:
                count = min(len(zeros), remaining)
                stream.write(zeros[:count])
                remaining -= count
            stream.flush()
            os.fsync(stream.fileno())
    except FileNotFoundError:
        return
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def staged_file(directory, prefix, data=None):
    """Yield a unique path, optionally initialized with bytes, then wipe/remove it.

    With ``data=None`` the yielded path is reserved but absent, for tools that
    create output files themselves. ``prefix`` should identify the caller and
    must not contain user-controlled data.
    """
    directory = Path(directory)
    descriptor, raw_path = tempfile.mkstemp(prefix=prefix, dir=directory)
    path = Path(raw_path)
    try:
        if data is None:
            os.close(descriptor)
            descriptor = None
            path.unlink()
        else:
            stream = os.fdopen(descriptor, "wb")
            descriptor = None
            with stream:
                stream.write(memoryview(data))
                stream.flush()
                os.fsync(stream.fileno())
        yield path
    finally:
        if descriptor is not None:
            os.close(descriptor)
        _wipe_and_unlink(path)
