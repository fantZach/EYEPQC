"""Capture and compare the source inputs used by the isolated G0 build."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "src/ps/src/m01_g0.c", "src/rtl/common/heartbeat.sv", "board/xdc/m01.xdc",
    "prj/build_m01.tcl", "prj/build_m01.ps1", "prj/build_g0.ps1",
    "prj/build_g0_software.py", "prj/build_software.py", "prj/generate_bsp.tcl",
    "prj/arm_startup.py", "prj/a9_ddr.ld", "prj/check_g0_implemented.tcl",
)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "check"))
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    target = args.manifest.resolve()
    current = {relative: digest(ROOT / relative) for relative in SOURCES}
    if args.mode == "capture":
        if target.exists():
            parser.error(f"refusing to overwrite source snapshot: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        print(f"G0_SOURCE_SNAPSHOT_OK {target}")
        return 0
    expected = json.loads(target.read_text(encoding="utf-8"))
    changed = [name for name in SOURCES if expected.get(name) != current[name]]
    if changed:
        raise SystemExit("G0_SOURCE_SNAPSHOT_CHANGED: " + ", ".join(changed))
    print(f"G0_SOURCE_SNAPSHOT_MATCH {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
