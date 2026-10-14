"""Optional probe tests; run with the separate p2p_venv, not the USB relay environment."""
import asyncio
import importlib.util
import json
import unittest
import sys
from pathlib import Path

from aiortc import RTCConfiguration, RTCPeerConnection

spec = importlib.util.spec_from_file_location("p2p_probe", Path(__file__).parents[1] / "src/host/p2p_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    def test_sdp_bounds(self):
        for data in [b"x" * 65537, b"[]", b"{}", b'{"type":"offer","sdp":7}']:
            with self.assertRaises((ValueError, TypeError)):
                probe.parse_description(data, "answer")
        for sdp in ["v=0\r\nm=audio 9 RTP/AVP 0\r\n", "v=0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\na=candidate:x typ relay\r\n"]:
            with self.assertRaises(ValueError):
                probe.parse_description(json.dumps({"type": "answer", "sdp": sdp}).encode(), "answer")

    def test_ack_bounds(self):
        import struct
        self.assertTrue(probe.valid_ack(struct.pack("!I", 1), 1))
        for value in [b"", b"12345", "DONE", struct.pack("!I", 0), struct.pack("!I", 2)]:
            self.assertFalse(probe.valid_ack(value, 1))

    async def test_real_local_datachannel(self):
        asyncio.get_running_loop().set_debug(False)
        sender = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        receiver = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        channel = sender.createDataChannel("eyepqc-probe", ordered=True)
        opened = asyncio.Event()
        channel.on("open", opened.set)
        received = []

        @receiver.on("datachannel")
        def datachannel(remote):
            @remote.on("message")
            def receive(message):
                import struct
                if isinstance(message, bytes):
                    self.assertEqual(message, probe.packet(len(received)))
                    received.append(message)
                    remote.send(struct.pack("!I", len(received)))
                else:
                    self.assertEqual(message, "END:" + str(len(received)))
                    remote.send("DONE")

        try:
            await sender.setLocalDescription(await sender.createOffer())
            offer = probe.parse_description(json.dumps({"type": "offer", "sdp": sender.localDescription.sdp}).encode(), "offer")
            await receiver.setRemoteDescription(offer)
            await receiver.setLocalDescription(await receiver.createAnswer())
            answer = probe.parse_description(json.dumps({"type": "answer", "sdp": receiver.localDescription.sdp}).encode(), "answer")
            await sender.setRemoteDescription(answer)
            await asyncio.wait_for(opened.wait(), 10)
            result = await probe.measure(channel, 1, 5)
            print("LOCAL_DATA_CHANNEL", json.dumps(result))
            self.assertEqual(result["outcome"], "PASS")
            self.assertEqual(result["verified_packets"], len(received))
            self.assertGreater(result["verified_packets"], 0)
        finally:
            await sender.close()
            await receiver.close()


if __name__ == "__main__":
    unittest.main()
