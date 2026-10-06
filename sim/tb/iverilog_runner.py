"""Strict Icarus wrapper for a known Windows process-teardown crash."""
import os
from pathlib import Path
import subprocess
import sys


WINDOWS_ACCESS_VIOLATION = 3221225477


def compile_iverilog(command, output):
    """Accept a teardown crash only when Icarus emitted a nonempty image.

    Callers must run that image with vvp and check their functional pass marker.
    """
    output = Path(output)
    result = subprocess.run(command)
    if result.returncode == 0:
        if output.is_file() and output.stat().st_size:
            return
        raise RuntimeError(f"Icarus returned success without a nonempty image: {output}")
    if (os.name == "nt" and result.returncode == WINDOWS_ACCESS_VIOLATION
            and output.is_file() and output.stat().st_size):
        print("WARNING: Icarus exited with Windows access violation after writing its image; "
              "vvp must still pass the caller's functional checks.", file=sys.stderr)
        return
    raise subprocess.CalledProcessError(result.returncode, command)
