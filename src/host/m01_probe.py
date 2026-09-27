"""Finite TCP echo soak. stdlib only; any mismatch/EOF/timeout fails the run."""
import argparse
import hashlib
import math
import socket
import time


def check_echo(sock, payload):
    # Interleave send/read so payloads larger than a TCP window cannot deadlock.
    for start in range(0, len(payload), 997):
        chunk = payload[start:start + 997]
        sock.sendall(chunk)
        received = bytearray()
        while len(received) < len(chunk):
            part = sock.recv(len(chunk) - len(received))
            if not part:
                raise ConnectionError("EOF before complete echo")
            received.extend(part)
        if received != chunk:
            raise ValueError(f"echo mismatch at offset {start}")


def run(host, port=7, seconds=1800, timeout=5):
    if (not math.isfinite(seconds) or not math.isfinite(timeout) or
            seconds <= 0 or timeout <= 0 or not 1 <= port <= 65535):
        raise ValueError("duration/timeout must be positive; port must be 1..65535")
    lengths = (1, 15, 16, 17, 31, 32, 1400, 1460, 8192, 65537)
    start = time.monotonic()
    rounds = total = 0
    while time.monotonic() - start < seconds:
        # Reconnect each round: checks FIN and connection cleanup as well as data.
        with socket.create_connection((host, port), timeout=timeout) as sock:
            for length in lengths:
                payload = hashlib.shake_256(f"M01:{rounds}:{length}".encode()).digest(length)
                check_echo(sock, payload)
                total += length
            sock.shutdown(socket.SHUT_WR)
            if sock.recv(1) != b"":
                raise ValueError("unexpected trailing echo bytes")
        rounds += 1
    result = {"host": host, "port": port, "rounds": rounds, "bytes": total,
              "elapsed_seconds": round(time.monotonic() - start, 3)}
    print("ECHO_PASS", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("--port", type=int, default=7)
    parser.add_argument("--seconds", type=float, default=1800)
    parser.add_argument("--timeout", type=float, default=5)
    args = parser.parse_args()
    run(args.host, args.port, args.seconds, args.timeout)
