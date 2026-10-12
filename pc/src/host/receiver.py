"""M12 offline replay of G3 board captures; USB live input is the next step."""
import argparse
from datetime import datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import struct
import time

from PIL import Image

from g3_board import CHUNK, MAGIC, decrypt_g3


def replay_frame(folder):
    if (folder / "request.bin").stat().st_size != 128 or (folder / "reply.bin").stat().st_size != 128:
        raise ValueError("G3 mailbox length mismatch")
    request = (folder / "request.bin").read_bytes()
    reply = (folder / "reply.bin").read_bytes()
    magic, state, _, status, length, chunks, sealed_length = struct.unpack_from("<7I", reply)
    if (int.from_bytes(request[:4], "little") != MAGIC or magic != MAGIC or state != 2 or
        status != 0 or not 4 <= length <= 65536 or chunks != (length + CHUNK - 1) // CHUNK):
        raise ValueError("Invalid G3 board reply")
    if reply[64:88] != bytes(24):
        raise ValueError("G3 board did not clear key/nonce")
    sealed_file = folder / "packets.enc"
    if sealed_length != length + 16 * chunks or not sealed_length <= sealed_file.stat().st_size <= 68096:
        raise ValueError("Encrypted G3 capture length mismatch")
    sealed = sealed_file.read_bytes()
    nonce_start = struct.unpack_from("<I", reply, 124)[0]
    frame = decrypt_g3(length, sealed[:sealed_length], request[64:80],
                       request[80:88], nonce_start)
    with Image.open(BytesIO(frame)) as image:
        image.load()
        dimensions = image.size
    original = folder / "frame.jpg"
    if original.is_file() and original.read_bytes()[:length] != frame:
        raise ValueError("Replayed frame differs from captured DDR JPEG")
    return frame, dimensions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="G3 capture directory or one frame_XXX directory")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--show", action="store_true", help="Open decoded images after verification")
    args = parser.parse_args()
    source = args.capture.resolve()
    folders = sorted(source.glob("frame_*")) if source.is_dir() and not (source / "reply.bin").exists() else [source]
    if not folders or any(not x.is_dir() for x in folders):
        parser.error("No G3 frame directories found")
    target = (args.output_dir or source / ("m12_replay_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))).resolve()
    if target.exists():
        parser.error("Output directory already exists")
    start = time.monotonic()
    verified = [(folder.name, *replay_frame(folder)) for folder in folders]
    target.mkdir(parents=True)
    records = []
    for name, frame, dimensions in verified:
        output = target / f"{name}.jpg"
        output.write_bytes(frame)
        records.append(dict(file=output.name, bytes=len(frame), width=dimensions[0],
                            height=dimensions[1], sha256=hashlib.sha256(frame).hexdigest()))
        if args.show:
            Image.open(BytesIO(frame)).show()
    elapsed = time.monotonic() - start
    (target / "result.json").write_text(json.dumps(dict(source=str(source),
        frames=records, processing_seconds=elapsed), indent=2) + "\n")
    print(f"M12_OFFLINE_OK frames={len(records)} elapsed_s={elapsed:.3f} output={target}")


if __name__ == "__main__":
    main()
