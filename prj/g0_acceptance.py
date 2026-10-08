"""Passive UART collector and evidence checker for the standalone M01 G0 image."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOT_RE = re.compile(r"^G0 BOOT build=([A-Za-z0-9_-]+) boot_mode=0x([0-9a-fA-F]+)")
STAT_RE = re.compile(
    r"^G0 STAT uptime_s=(\d+) ticks=(\d+) ddr_pass=(\d+) ddr_err=(\d+) "
    r"assert=(\d+) exception=(\d+) timer_err=(\d+) boot_mode=0x([0-9a-fA-F]+)"
)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path):
    path = Path(path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("board_validated") is not False:
        raise ValueError("manifest board_validated must remain false until physical acceptance")
    if manifest.get("network_init") is not False or manifest.get("usb_init") is not False:
        raise ValueError("G0 image must not initialize network or USB")
    if manifest.get("development_key_or_seed_required") is not False:
        raise ValueError("G0 startup image must not depend on injected key material")
    xsa = Path(manifest["xsa"])
    if not xsa.is_file() or sha256(xsa) != manifest["xsa_sha256"]:
        raise ValueError("XSA missing or hash differs from G0 manifest")
    boot = Path(manifest["boot_bin"])
    if not boot.is_file() or sha256(boot) != manifest["boot_bin_sha256"]:
        raise ValueError("G0 BOOT.BIN missing or hash differs from manifest")
    bsp_library = Path(manifest.get("bsp_library", ""))
    if not bsp_library.is_file() or sha256(bsp_library) != manifest.get("bsp_sha256"):
        raise ValueError("generated BSP libxil.a missing or hash differs from G0 manifest")
    workspace = path.parent
    for relative, expected in manifest.get("artifacts", {}).items():
        target = workspace / relative
        if not target.is_file() or sha256(target) != expected:
            raise ValueError(f"build artifact missing or hash differs from manifest: {relative}")
    for relative, expected in manifest.get("source_inputs", {}).items():
        target = ROOT / relative
        if not target.is_file() or sha256(target) != expected:
            raise ValueError(f"G0 build source changed since image was made: {relative}")
    for filename, expected in manifest.get("bsp_interface_files", {}).items():
        target = Path(filename)
        if not target.is_file() or sha256(target) != expected:
            raise ValueError(f"generated BSP interface changed since image was made: {filename}")
    evidence = manifest.get("implementation_evidence", {})
    for key, hash_key in (("summary", "summary_sha256"), ("io_report", "io_report_sha256"),
                          ("clock_report", "clock_report_sha256")):
        target = Path(evidence.get(key, ""))
        if not target.is_file() or sha256(target) != evidence.get(hash_key):
            raise ValueError(f"G0 implementation evidence missing or changed: {key}")
    if (evidence.get("led_package_pin") != "H15" or
            evidence.get("led_iostandard") != "LVCMOS33" or
            abs(float(evidence.get("heartbeat_clock_period_ns", 0)) - 10.0) > 0.01):
        raise ValueError("manifest does not bind G0 LED to implemented H15/100 MHz evidence")
    return manifest


def read_log(path):
    rows = []
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            row = {"line": raw}
        if isinstance(row, dict):
            rows.append(row)
    return rows


def verify_log(path, scenario, manifest=None, minimum_seconds=1800):
    rows = read_log(path)
    lines = [str(row.get("line", "")).strip() for row in rows if row.get("line")]
    failures = []
    disconnects = [row for row in rows if row.get("event") == "uart_disconnected"]
    reconnects = [row for row in rows if row.get("event") == "uart_reconnected"]
    if disconnects:
        failures.append(f"UART reader disconnected {len(disconnects)} time(s); evidence is not continuous")
    if len(reconnects) > 1:
        failures.append(f"UART reader reconnected {len(reconnects) - 1} time(s); evidence is not continuous")
    segments = []
    for line in lines:
        if "G0 FAIL" in line or "G0 ASSERT" in line or "G0 EXCEPTION" in line:
            failures.append("target reported failure: " + line)
        boot = BOOT_RE.match(line)
        if boot:
            segments.append({"build_id": boot.group(1), "boot_mode": int(boot.group(2), 16),
                             "ddr_pass_marker": False, "timer_pass_marker": False,
                             "ready_marker": False, "stats": []})
            continue
        if not segments:
            if line.startswith("G0 "):
                failures.append("G0 output appeared before a BOOT marker")
            continue
        current = segments[-1]
        if line.startswith("G0 DDR PASS "):
            current["ddr_pass_marker"] = True
        if line.startswith("G0 TIMER PASS "):
            current["timer_pass_marker"] = True
        if line.startswith("G0 READY "):
            current["ready_marker"] = True
        stat = STAT_RE.match(line)
        if stat:
            values = tuple(int(value, 16) if index == 7 else int(value)
                           for index, value in enumerate(stat.groups()))
            current["stats"].append(dict(zip(("uptime_s", "ticks", "ddr_pass", "ddr_err", "assert",
                                               "exception", "timer_err", "boot_mode"), values)))

    if not segments:
        failures.append("no G0 BOOT marker captured")
    for index, segment in enumerate(segments, start=1):
        if not segment["ddr_pass_marker"]:
            failures.append(f"boot segment {index} has no DDR PASS marker")
        if not segment["timer_pass_marker"]:
            failures.append(f"boot segment {index} has no TIMER PASS marker")
        if not segment["ready_marker"]:
            failures.append(f"boot segment {index} has no READY marker")
        if not segment["stats"]:
            failures.append(f"boot segment {index} has no periodic STAT sample")

    build_ids = {segment["build_id"] for segment in segments}
    boot_modes = {segment["boot_mode"] for segment in segments}
    expected_id = manifest.get("build_id") if manifest else None
    if expected_id and build_ids != {expected_id}:
        failures.append(f"boot image id differs from manifest: expected {expected_id}, got {sorted(build_ids)}")

    if scenario in ("sd_cold_start_30m", "jtag_led_probe") and len(segments) != 1:
        failures.append(f"cold run had {len(segments)} application boots; expected exactly one")
    if scenario == "reset_probe" and len(segments) != 2:
        failures.append(f"reset probe had {len(segments)} application boots; expected exactly two")

    for index, segment in enumerate(segments, start=1):
        if scenario in ("sd_cold_start_30m", "reset_probe") and segment["boot_mode"] != 0x05:
            failures.append(f"boot segment {index} BOOT_MODE is not SD0 (expected 0x05)")
        previous = None
        for sample in segment["stats"]:
            if sample["boot_mode"] != segment["boot_mode"]:
                failures.append(f"boot segment {index} STAT boot mode differs from BOOT marker")
            if any(sample[name] != 0 for name in ("ddr_err", "assert", "exception", "timer_err")):
                failures.append(f"nonzero fault counter at uptime {sample['uptime_s']}s in boot segment {index}")
            if previous:
                delta_s = sample["uptime_s"] - previous["uptime_s"]
                delta_ticks = sample["ticks"] - previous["ticks"]
                if delta_s <= 0 or not 18 * delta_s <= delta_ticks <= 22 * delta_s:
                    failures.append(f"timer tick rate/uptime discontinuity near {sample['uptime_s']}s in boot segment {index}")
                if delta_s > 30:
                    failures.append(f"UART/stat gap of {delta_s}s near uptime {sample['uptime_s']}s in boot segment {index}")
            previous = sample
        if segment["stats"]:
            final = segment["stats"][-1]
            expected_ddr_passes = 2 + final["uptime_s"] // 60
            if final["ddr_pass"] < expected_ddr_passes:
                failures.append(f"periodic DDR tests incomplete in boot segment {index}: "
                                f"{final['ddr_pass']} < {expected_ddr_passes}")
            if scenario in ("sd_cold_start_30m", "jtag_led_probe") and index == 1:
                if segment["stats"][0]["uptime_s"] > 30:
                    failures.append("first periodic sample was later than 30s; startup evidence window missed")
                if final["uptime_s"] < minimum_seconds:
                    failures.append(f"runtime {final['uptime_s']}s is below required {minimum_seconds}s")

    observation = next((row for row in reversed(rows)
                        if row.get("event") == "operator_observation"), {})
    if observation.get("led_1hz_seen") is not True:
        failures.append("operator did not confirm the H15 LED heartbeat visually")
    if scenario == "reset_probe" and observation.get("reset_pressed_once") is not True:
        failures.append("operator reset-button action was not confirmed")
    if scenario == "sd_cold_start_30m":
        for field, description in (("sd_card_prepared", "SD card with this BOOT.BIN"),
                                   ("sd_boot_straps_confirmed", "board-revision SD boot straps"),
                                   ("cold_power_cycle_confirmed", "full power-off/on cycle")):
            if observation.get(field) is not True:
                failures.append(f"operator did not confirm {description}")

    return {
        "status": "passed" if not failures else "failed",
        "scenario": scenario,
        "minimum_runtime_s": minimum_seconds if scenario in ("sd_cold_start_30m", "jtag_led_probe") else None,
        "boot_count": len(segments),
        "build_ids": sorted(build_ids),
        "boot_modes": [f"0x{mode:02x}" for mode in sorted(boot_modes)],
        "stat_samples": sum(len(segment["stats"]) for segment in segments),
        "final_uptime_s": segments[-1]["stats"][-1]["uptime_s"] if segments and segments[-1]["stats"] else None,
        "final_ddr_passes": segments[-1]["stats"][-1]["ddr_pass"] if segments and segments[-1]["stats"] else None,
        "failures": failures,
    }


def write_record(writer, record):
    writer.write(json.dumps(record, ensure_ascii=False) + "\n")
    writer.flush()


def capture(args):
    manifest = load_manifest(args.manifest)
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError("pyserial is required; install the repository requirements") from exc
    output = Path(args.output) if args.output else ROOT / "data/captures/g0" / (
        datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{args.scenario}.jsonl")
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"G0 镜像：build={manifest['build_id']}，SD0 BOOT.BIN={manifest['boot_bin']}")
    print("采集器只读：不发送 UART 字节、不触发复位、不写 SD/Flash、不操作 JTAG。")
    if args.scenario == "sd_cold_start_30m":
        print("请先使用专用 SD 卡并把此 BOOT.BIN 放在卡根目录；按板卡版本手册准备 SD 启动跳帽/拨码。")
        print("串口实际连接并显示‘UART 已就绪’后，才完整断电再上电；保持运行至少 30 分钟。")
    elif args.scenario == "jtag_led_probe":
        print("请预先准备经批准的临时 JTAG 加载流程；采集器打开 UART 后才提示你加载。")
        print("本探测只验证软件启动/DDR/timer/LED，BOOT_MODE不要求SD0，也不验收SD启动。")
    else:
        print("先准备好通过已批准方式启动 G0；看到本工具提示‘UART 已就绪’后启动。")
        print("程序输出 READY 后，本工具才提示你按一次复位键。它不会替你复位。")
    input("确认以上物理操作已准备好后按 Enter 开始 UART 只读采集：")

    port = serial.Serial(port=None, baudrate=115200, bytesize=8, parity="N", stopbits=1,
                         timeout=0.5, write_timeout=0.5)
    port.port = args.port
    port.dtr = False
    port.rts = False
    lost_since = None
    opened = False
    deadline = None
    try:
        # Exclusive creation preserves prior evidence. Do not allow a rerun to overwrite it.
        with output.open("x", encoding="utf-8", newline="\n") as writer:
            write_record(writer, {"event": "capture_started", "scenario": args.scenario,
                                  "port": args.port, "build_id": manifest["build_id"],
                                  "wall_utc": datetime.now(timezone.utc).isoformat(),
                                  "requested_seconds": args.seconds})
            reset_prompted = False
            while deadline is None or time.monotonic() < deadline:
                try:
                    if not port.is_open:
                        had_opened = opened
                        port.open()
                        opened = True
                        lost_since = None
                        if deadline is None:
                            deadline = time.monotonic() + args.seconds
                        write_record(writer, {"event": "uart_reconnected" if had_opened else "uart_connected",
                                              "wall_utc": datetime.now(timezone.utc).isoformat()})
                        if had_opened:
                            print(f"UART 已重连 port={args.port}；本次断线会使验收证据判失败。")
                        else:
                            print(f"UART 已就绪 port={args.port}。")
                        if args.scenario == "sd_cold_start_30m" and not had_opened:
                            print("现在完整断电再上电；请勿拔掉 UART 采集器。")
                        elif args.scenario == "jtag_led_probe" and not had_opened:
                            print("UART 已就绪；现在按获批流程临时加载 G0 镜像。")
                        elif args.scenario == "reset_probe" and not had_opened:
                            print("现在通过 SD/批准的启动方式启动 G0；看到 READY 后再按复位键。")
                    raw = port.readline()
                except (OSError, serial.SerialException) as exc:
                    if lost_since is None:
                        lost_since = time.monotonic()
                        write_record(writer, {"event": "uart_disconnected",
                                              "wall_utc": datetime.now(timezone.utc).isoformat(),
                                              "detail": str(exc)[:160]})
                    try:
                        port.close()
                    except OSError:
                        pass
                    if time.monotonic() - lost_since > args.reconnect_seconds:
                        raise RuntimeError("UART did not reconnect before timeout") from exc
                    time.sleep(0.5)
                    continue
                if raw:
                    line = raw.decode("ascii", errors="replace").rstrip("\r\n")
                    write_record(writer, {"wall_utc": datetime.now(timezone.utc).isoformat(),
                                          "line": line})
                    print(line)
                    if (args.scenario == "reset_probe" and not reset_prompted and
                            line.startswith("G0 READY ")):
                        input("已捕获首次 G0 READY。请按 Enter 后按板卡手册确认的复位键恰好一次：")
                        reset_prompted = True
                    stat = STAT_RE.match(line)
                    if (args.scenario in ("sd_cold_start_30m", "jtag_led_probe") and stat and
                            int(stat.group(1)) >= args.minimum_seconds):
                        break
                    if args.scenario == "reset_probe" and BOOT_RE.match(line):
                        observed_boots = sum(1 for saved in read_log(output)
                                             if BOOT_RE.match(str(saved.get("line", ""))))
                        if observed_boots >= 2:
                            break
            if not opened:
                raise RuntimeError("UART 串口从未成功打开")
            led = input("你是否亲眼看到 H15 LED 稳定约 1 Hz 闪烁？输入 yes/no：")
            observation = {"event": "operator_observation",
                           "wall_utc": datetime.now(timezone.utc).isoformat(),
                           "led_1hz_seen": led.strip().lower() == "yes"}
            if args.scenario == "reset_probe":
                reset = input("你是否按板卡手册确认的复位键恰好一次？输入 yes/no：")
                observation["reset_pressed_once"] = reset.strip().lower() == "yes"
            if args.scenario == "sd_cold_start_30m":
                sd = input("是否在专用 SD 卡根目录使用了本次这个 BOOT.BIN？输入 yes/no：")
                straps = input("是否按对应板卡版本手册确认 SD 启动跳帽/拨码？输入 yes/no：")
                power = input("运行前是否完全断电后重新上电？输入 yes/no：")
                observation.update(sd_card_prepared=sd.strip().lower() == "yes",
                                   sd_boot_straps_confirmed=straps.strip().lower() == "yes",
                                   cold_power_cycle_confirmed=power.strip().lower() == "yes")
            write_record(writer, observation)
    finally:
        port.close()

    result = verify_log(output, args.scenario, manifest, args.minimum_seconds)
    result["log"] = str(output)
    result["manifest"] = str(Path(args.manifest).resolve())
    result_path = output.with_suffix(".result.json")
    with result_path.open("x", encoding="utf-8", newline="\n") as result_file:
        result_file.write(json.dumps(result, indent=2) + "\n")
    print("G0_ACCEPTANCE_" + result["status"].upper(), result_path)
    if result["failures"]:
        for reason in result["failures"]:
            print("G0_FAIL", reason)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    preflight = sub.add_parser("preflight", help="verify G0 artifacts offline")
    preflight.add_argument("--manifest", required=True, type=Path)
    verify = sub.add_parser("verify", help="verify a saved UART JSONL log")
    verify.add_argument("--manifest", required=True, type=Path)
    verify.add_argument("--log", required=True, type=Path)
    verify.add_argument("--scenario", choices=("jtag_led_probe", "sd_cold_start_30m", "reset_probe"), required=True)
    verify.add_argument("--minimum-seconds", type=int, default=1800)
    run = sub.add_parser("capture", help="passively capture a physical G0 acceptance run")
    run.add_argument("--manifest", required=True, type=Path)
    run.add_argument("--port", required=True, help="explicit PS UART COM port; no auto-selection")
    run.add_argument("--scenario", choices=("jtag_led_probe", "sd_cold_start_30m", "reset_probe"), required=True)
    run.add_argument("--seconds", type=int, default=2100,
                     help="capture timeout; SD run stops after target uptime is observed")
    run.add_argument("--minimum-seconds", type=int, default=1800)
    run.add_argument("--reconnect-seconds", type=int, default=120)
    run.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "preflight":
        manifest = load_manifest(args.manifest)
        print(f"G0_PREFLIGHT_OK build={manifest['build_id']} boot={manifest['boot_bin_sha256']}")
        print("board_validated=false; no board or card was accessed")
        return 0
    if args.command == "verify":
        manifest = load_manifest(args.manifest)
        result = verify_log(args.log, args.scenario, manifest, args.minimum_seconds)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "passed" else 1
    if args.seconds <= 0 or args.minimum_seconds <= 0 or args.reconnect_seconds < 0:
        parser.error("seconds/minimum-seconds must be positive and reconnect-seconds nonnegative")
    result = capture(args)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
