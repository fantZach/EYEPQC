"""Exercise real G6 static control/timer functions with existing SDK mocks."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "sim/tb"))
from test_g6_cleanup_paths import find_native_gcc


class Firmware(unittest.TestCase):
    def test_real_control_and_deadlines(self):
        original = (ROOT / "sim/tb/test_g6_cleanup_paths.c").read_text()
        original = original.replace('#include "../../board/src/ps/src/g6_usb.c"',
                                    '#include "' + (ROOT / "board/src/ps/src/g6_usb.c").as_posix() + '"')
        original = original.replace("int main(void)", "int baseline_harness_main(void)")
        original = original.replace("int eye_mlkem_check_sk(", "int mock_identity_check_sk(")
        original = original.replace("int eye_mlkem_dec(", "int mock_identity_dec(")
        cases = r'''
#include <assert.h>
int test_mlkem_enc_derand(uint8_t *, uint8_t *, const uint8_t *, const uint8_t *);
int main(void) {
    uint8_t message[844] = {0}, body[832] = {0}, tag[32], input[1739];
    uint8_t shared[32], encaps_coins[32] = {0};
    setup_case(WAIT_FINISHED, EYE_STATE_CONFIRM);
    negotiated_suite = 2; business_ready = 0;
    session.board_finished_sent = 1;
    assert(!eye_hmac_sha256(tag, session.control_key, 32,
                           (const uint8_t *)"host finished", 13));
    memcpy(input, "host finished", 13);
    memcpy(input + 13, session.transcript_hash, 32);
    assert(!eye_hmac_sha256(tag, session.control_key, 32, input, 45));
    assert(!eye_control_encode(message, sizeof message, EYE_FINISHED_HOST, tag, 32));
    assert(!handle_control(message, 44));
    assert(phase == WAIT_EPHEMERAL && ephemeral.active);
    assert(words_are_zero(session.video_key, 16));
    uint8_t early_start[52];
    assert(!eye_control_encode(early_start, 52, EYE_START, body, 40));
    assert(handle_control(early_start, 52));
    memcpy(body, session.transcript_hash, 32);
    assert(!test_mlkem_enc_derand(body + 32, shared, ephemeral.offer + 44, encaps_coins));
    assert(!eye_control_encode(message, sizeof message, EYE_EPHEMERAL_REPLY, body, sizeof body));
    memcpy(input, "EYEPQC eph reply v1", 19);
    memcpy(input + 19, session.transcript_hash, 32);
    memcpy(input + 51, ephemeral.offer, 876);
    memcpy(input + 927, message, 812);
    assert(!eye_hmac_sha256(message + 812, session.control_key, 32, input, sizeof input));
    assert(!handle_control(message, sizeof message));
    assert(phase == WAIT_FINISHED && business_ready);
    assert(words_are_zero((const uint8_t *)&ephemeral, sizeof ephemeral));
    assert(!session.host_finished_verified && session.board_finished_sent);
    assert(handle_control(early_start, 52));
    assert(handle_control(message, sizeof message)); /* duplicate reply rejected */
    memcpy(input, "host finished", 13);
    memcpy(input + 13, session.transcript_hash, 32);
    assert(!eye_hmac_sha256(tag, session.control_key, 32, input, 45));
    assert(!eye_control_encode(message, sizeof message, EYE_FINISHED_HOST, tag, 32));
    assert(!handle_control(message, 44) && phase == WAIT_START);

    setup_case(STREAM, EYE_STATE_STREAMING);
    negotiated_suite = 2; business_ready = 1; profile_started = 123;
    assert(!expire_profile(123 + 1800ULL * COUNTS_PER_SECOND - 1));
    assert(phase == STREAM && !words_are_zero(session.video_key, 16));
    assert(expire_profile(123 + 1800ULL * COUNTS_PER_SECOND));
    assert(phase == WAIT_HELLO && !business_ready);
    assert(words_are_zero(session.control_key, 32) && words_are_zero(session.video_key, 16));
    uint8_t hello_body[36] = {1,1,0,2};
    assert(!eye_control_encode(message, sizeof message, EYE_HELLO, hello_body, 36));
    assert(!handle_control(message, 48) && phase == WAIT_KEM && ack[15] == 2);
    assert(!expire_profile(15ULL * COUNTS_PER_SECOND - 1));
    memset(ephemeral.private_key, 0xaa, sizeof ephemeral.private_key);
    assert(expire_profile(15ULL * COUNTS_PER_SECOND));
    assert(phase == FAULT && words_are_zero((const uint8_t *)&ephemeral, sizeof ephemeral));
    setup_case(STREAM, EYE_STATE_STREAMING);
    negotiated_suite = 1; profile_started = 0;
    assert(!expire_profile(1800ULL * COUNTS_PER_SECOND));
    assert(phase == STREAM);
    setup_case(WAIT_EPHEMERAL, EYE_STATE_CONFIRM);
    negotiated_suite = 2;
    memset(ephemeral.private_key, 0xaa, sizeof ephemeral.private_key);
    ephemeral.active = 1;
    assert(!retire_disconnected_session(0, 0, 0, 1));
    assert(phase == WAIT_HELLO);
    assert(words_are_zero((const uint8_t *)&ephemeral, sizeof ephemeral));
    assert(words_are_zero(session.control_key, 32));
    puts("EPHEMERAL_FIRMWARE_PASS");
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / "xil_printf.h").write_text("int xil_printf(const char *, ...);\n")
            (out / "xtime_l.h").write_text("#include <stdint.h>\ntypedef uint64_t XTime;\n#define COUNTS_PER_SECOND 1000000ULL\nstatic inline void XTime_GetTime(XTime *t) { *t=0; }\n")
            (out / "xil_cache.h").write_text("#include <stdint.h>\nvoid Xil_DCacheFlushRange(uintptr_t, uint32_t);\n")
            harness = out / "harness.c"
            harness.write_text(original + cases)
            reference = out / "reference.c"
            reference.write_text('#define MLK_CONFIG_PARAMETER_SET 512\n#define MLK_CONFIG_NAMESPACE_PREFIX test_mlkem\n'
                                 '#define MLK_CONFIG_NO_RANDOMIZED_API\n#define MLK_CONFIG_NO_SUPERCOP\n#include "mlkem_native.c"\n')
            include = [out, *[ROOT / name for name in ("board/src/ps/include", "board/src/third_party", "board/src/third_party/mlkem", "board/src/third_party/tinycrypt/lib/include")]]
            sources = [harness, reference, *[ROOT / "board/src/ps/src" / name for name in ("ephemeral.c", "m09_mlkem.c", "session.c", "protocol.c")],
                       *[ROOT / "board/src/third_party/tinycrypt/lib/source" / name for name in ("sha256.c", "utils.c")]]
            compiler = find_native_gcc()
            self.assertTrue(compiler)
            for profile in ([], ["-DG6_SECURE_CLEANUP"]):
                command = [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                           *profile, *[arg for path in include for arg in ("-I", str(path))],
                           *map(str, sources), "-o", str(out / "test.exe")]
                built = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(built.returncode, 0, built.stderr)
                ran = subprocess.run([str(out / "test.exe")], capture_output=True, text=True)
                self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
                self.assertIn("EPHEMERAL_FIRMWARE_PASS", ran.stdout)

    def test_production_entropy_and_no_legacy_fallback(self):
        source = (ROOT / "sim/tb/test_g6_production_profile.c").read_text()
        source = source.replace('#include "../../board/src/ps/src/g6_usb.c"', '#include "' + (ROOT / "board/src/ps/src/g6_usb.c").as_posix() + '"')
        source = source.replace("int main(void)", "int baseline_harness_main(void)")
        source += r'''
#include <assert.h>
int main(void) {
    uint8_t message[48], body[36] = {1,1,0,1}, coins[64];
    reset_provider();
    assert(!initialize_production_security());
    phase = WAIT_HELLO;
    assert(!eye_control_encode(message, sizeof message, EYE_HELLO, body, sizeof body));
    assert(handle_control(message, sizeof message) && usb_send_calls == 0);
    provider_entropy_status = 0;
    assert(!ephemeral_coins(coins));
    assert(bytes_are(coins, sizeof coins, 0xa7));
    provider_entropy_status = 9;
    memset(coins, 0x55, sizeof coins);
    assert(ephemeral_coins(coins));
    assert(bytes_are(coins, sizeof coins, 0));
    memset(&ephemeral, 0xaa, sizeof ephemeral);
    fail_closed();
    assert(phase == FAULT && provider_shutdown_calls);
    assert(bytes_are((const uint8_t *)&ephemeral, sizeof ephemeral, 0));
    assert(bytes_are(session.control_key, sizeof session.control_key, 0));
    puts("EPHEMERAL_PRODUCTION_PASS");
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / "xil_printf.h").write_text("int xil_printf(const char *, ...);\n")
            (out / "xtime_l.h").write_text("#include <stdint.h>\ntypedef uint64_t XTime;\n#define COUNTS_PER_SECOND 1000000ULL\nstatic inline void XTime_GetTime(XTime *t) { *t=0; }\n")
            (out / "xil_cache.h").write_text("#include <stdint.h>\ntypedef uintptr_t UINTPTR;\nvoid Xil_DCacheFlushRange(UINTPTR, unsigned);\n")
            harness = out / "production.c"
            harness.write_text(source)
            include = [out, *[ROOT / name for name in ("board/src/ps/include", "board/src/third_party", "board/src/third_party/mlkem", "board/src/third_party/tinycrypt/lib/include")]]
            sources = [harness, *[ROOT / "board/src/ps/src" / name for name in ("ephemeral.c", "m09_mlkem.c", "session.c", "protocol.c", "g6_hmac_drbg.c")],
                       *[ROOT / "board/src/third_party/tinycrypt/lib/source" / name for name in ("sha256.c", "utils.c")]]
            compiler = find_native_gcc()
            self.assertTrue(compiler)
            built = subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-DG6_PRODUCTION", "-DG6_SECURE_CLEANUP",
                                    *[arg for path in include for arg in ("-I", str(path))], *map(str, sources), "-o", str(out / "test.exe")], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(out / "test.exe")], capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn("EPHEMERAL_PRODUCTION_PASS", ran.stdout)


if __name__ == "__main__":
    unittest.main()
