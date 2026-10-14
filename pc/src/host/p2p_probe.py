"""Manual SDP / STUN-only WebRTC probe. Synthetic bytes only; never opens USB."""
import argparse
import asyncio
import json
import struct
import sys
import time
from pathlib import Path

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription

PACKET_BYTES = 1459
MAX_SDP_BYTES = 65536
QUEUE_BYTES = 65536


def parse_description(data, expected):
    if len(data) > MAX_SDP_BYTES:
        raise ValueError("SDP file too large")
    value = json.loads(data)
    if not isinstance(value, dict) or set(value) != {"type", "sdp"}:
        raise ValueError("SDP JSON fields")
    sdp = value["sdp"]
    if value["type"] != expected or not isinstance(sdp, str) or not sdp.startswith("v=0\r\n"):
        raise ValueError("SDP type/header")
    media = [line for line in sdp.splitlines() if line.startswith("m=")]
    if len(media) != 1 or not media[0].startswith("m=application ") or " typ relay" in sdp:
        raise ValueError("data-only, no-relay SDP required")
    return RTCSessionDescription(sdp=sdp, type=expected)


def packet(sequence):
    return struct.pack("!I", sequence) + bytes([sequence % 251]) * (PACKET_BYTES - 4)


def valid_ack(message, sent):
    return isinstance(message, bytes) and len(message) == 4 and 0 < struct.unpack("!I", message)[0] <= sent


async def measure(channel, seconds, mbps, timeout=15):
    sent = acked = 0
    complete = asyncio.Event()
    error = None

    @channel.on("message")
    def receive(message):
        nonlocal acked, error
        if valid_ack(message, sent):
            count = struct.unpack("!I", message)[0]
            if count < acked:
                error = "ACK went backwards"
                complete.set()
            acked = max(acked, count)
        elif isinstance(message, str) and message == "DONE" and sent and acked == sent:
            complete.set()
        else:
            error = "invalid ACK or completion"
            complete.set()

    started = time.monotonic()
    interval = PACKET_BYTES * 8 / (mbps * 1_000_000)
    while time.monotonic() - started < seconds:
        if error or channel.readyState != "open":
            raise RuntimeError(error or "channel closed")
        while channel.bufferedAmount + PACKET_BYTES > QUEUE_BYTES:
            if time.monotonic() - started > seconds + timeout or channel.readyState != "open":
                raise TimeoutError("bounded send queue stalled")
            await asyncio.sleep(0.005)
        channel.send(packet(sent))
        sent += 1
        await asyncio.sleep(max(0, started + sent * interval - time.monotonic()))
    send_span = time.monotonic() - started
    channel.send("END:" + str(sent))
    await asyncio.wait_for(complete.wait(), timeout)
    if error or acked != sent:
        raise RuntimeError(error or "incomplete receive")
    confirmed_span = time.monotonic() - started
    return {"outcome": "PASS", "scope": "synthetic datachannel only, not camera/ML-KEM/Android video",
            "sent_packets": sent, "verified_packets": acked, "packet_bytes": PACKET_BYTES,
            "send_span_seconds": send_span, "confirmed_span_seconds": confirmed_span,
            "confirmed_mbps": sent * PACKET_BYTES * 8 / confirmed_span / 1_000_000,
            "target_mbps": mbps, "turn_configured": False}


async def run(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    ice = [] if args.stun == "none" else [RTCIceServer(urls=args.stun)]
    pc = RTCPeerConnection(RTCConfiguration(iceServers=ice))
    channel = pc.createDataChannel("eyepqc-probe", ordered=True)
    opened = asyncio.Event()
    channel.on("open", opened.set)
    try:
        await asyncio.wait_for(pc.setLocalDescription(await pc.createOffer()), 30)
        offer = {"type": pc.localDescription.type, "sdp": pc.localDescription.sdp}
        parse_description(json.dumps(offer).encode(), "offer")
        (output / "offer.json").write_text(json.dumps(offer), encoding="utf-8")
        print("P2P_OFFER_READY", output / "offer.json", flush=True)
        print("Keep this process running. Put phone answer in", output / "answer.json", flush=True)
        deadline = time.monotonic() + args.wait_seconds
        answer_path = output / "answer.json"
        while not answer_path.exists():
            if time.monotonic() > deadline:
                raise TimeoutError("manual answer deadline")
            await asyncio.sleep(0.5)
        # shortcut: manual file exchange, add authenticated signaling only after direct-path acceptance.
        if answer_path.stat().st_size > MAX_SDP_BYTES:
            raise ValueError("SDP file too large")
        await pc.setRemoteDescription(parse_description(answer_path.read_bytes(), "answer"))
        await asyncio.wait_for(opened.wait(), 45)
        print("P2P_DATA_CHANNEL_OPEN (no TURN configured)", flush=True)
        result = await measure(channel, args.seconds, args.mbps)
        (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("P2P_PROBE_OK", json.dumps(result), flush=True)
    except Exception as exc:
        (output / "result.json").write_text(json.dumps({"outcome": "FAIL", "error": type(exc).__name__,
                                                      "scope": "synthetic datachannel probe"}), encoding="utf-8")
        raise
    finally:
        await asyncio.wait_for(pc.close(), 5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="new ignored directory, e.g. tmp/p2p_run_1")
    parser.add_argument("--stun", default="stun:stun.cloudflare.com:3478")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--mbps", type=float, default=5)
    parser.add_argument("--wait-seconds", type=float, default=600)
    args = parser.parse_args()
    if not (1 <= args.seconds <= 120 and 0.1 <= args.mbps <= 10 and 30 <= args.wait_seconds <= 900):
        parser.error("seconds 1..120, mbps 0.1..10, wait-seconds 30..900")
    if args.stun != "none" and not args.stun.startswith("stun:"):
        parser.error("STUN only; TURN is intentionally excluded")
    if sys.platform == "win32":
        # This host's Proactor UDP close waits indefinitely; Selector releases sockets.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
