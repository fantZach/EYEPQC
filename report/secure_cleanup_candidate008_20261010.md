# G6/G3 安全清理候选 008 实板证据

日期：2026-10-10。本文记录 candidate008_retry1 的定向实板功能与清零读回证据。它缩小了指定共享缓冲区在正常 STOP 路径上的残留范围，**不构成生产安全验收**。

## 构建身份

实测工作区为 `build/vitis/g6_security_cleanup_20261010_candidate008_retry1`。候选 ELF 为 `g6_usb/build/g6_usb.elf`，SHA-256 `ebfb820b220de668b88db5634cfcb4feb1848dd08db006d3bcdaa5faee78ec03`；build manifest SHA-256 `8ad4b401f4a5c9604442267571bd9c8bf557a7fc79a154a3a15456d4a9c28ad3`，XSA SHA-256 `46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`。本次 `verify-only` 对 186 项通过。

候选 G6 源 `src/ps/src/g6_usb.c` SHA-256 为 `5782693f71c4ba8b4a439ced710112a5763fbf09b1e75a3009baa8ce1b52f1e2`。`source_baseline_manifest.json` 明确把候选绑定到 accepted G6 manifest（SHA-256 `8363a42eba7ec44525feadcf6c4120022dcf06a22fe5b440601d05ada29238db`）并记录源文件已修改；不冒称与 accepted 源码相同。候选 build manifest 的 `board_validated=false` 是构建时字段；下列实板证据作为独立记录，不回写构建身份。

目标符号范围经 `nm` 核对：诊断结构 108 B；`g3_frame` 65,600 B；`g3_sealed` 68,096 B；USB `tx` 1,472 B。手工 ARM 目标反汇编抽查了 DMA/GCM 停止门禁、frame/sealed 清除、USB TX 清除与 IRQ 状态恢复路径。该抽查不覆盖所有调用路径、寄存器或复位状态。

## 实板正常 STOP 与 DDR 读回

根代理使用 candidate008_retry1 完成一个约 3 秒会话并执行 authenticated STOP/drain。会话实际持续 2.9216 秒，输出 140 帧、约 47.577 fps。对应脱敏后的结果记录为 `data/captures/g6_usb_20261010_183800_671508/result.json`，SHA-256 `90f44f9966e4fa52216b28fbca1e42e06e3e3ee2db4259cc5c1271b8fd948900`。

随后只读诊断报告 stage 6、result 0、route mode 3、DMA reset 状态 0；capture RX、crypto RX、crypto TX 状态均为 1（HALTED/IDLE 安全状态），GCM status 为 0。USB quiesce、FLUSH、PRIME、completion clear 与 endpoint rebuild status 均为 0；FLUSH/PRIME 各轮询 1 次（上限各 256）。DDR 对象级 OR 读回结果：

| 对象 | 地址 | 全容量 | 读回 |
|---|---:|---:|---|
| `g3_frame` | `0x001319c0` | 65,600 B | OR=0 |
| `g3_sealed` | `0x00120fc0` | 68,096 B | OR=0 |
| USB `tx` | `0x00141bc0` | 1,472 B | OR=0 |
| **合计** |  | **135,168 B** | **全零** |

原始采集日志 `build/continuation_20261010/cleanup008_stop.stdout.log` 的 SHA-256 为 `d46112c95bf055340ed6d60ec4a6ae917974b802ff68dfa5ca3d1448042f6c47`，记录 `G6_CLEANUP_READBACK_PASS`。此证据只覆盖列出的三个 PS 可读 DDR 区域和此次正常 STOP 时点；`PL GCM full readback` 明确未证明。它不证明 CPU 寄存器/spill、描述符之外的缓存副本、PL 内部流水、异常复位/掉电或全域设备清零。

## Host exit 与仍在进行的恢复轮次

首轮 host-exit 回归在一个新会话 93 帧后正常结束。脱敏结果 `data/captures/g6_usb_20261010_184028_144519/result.json` SHA-256 为 `fef63ae615d65f2e27dab4a525809e9979e6ffc3da1ddbd13509d1d712c65fd0`。前后健康快照的 fatal/control/transport error counters 均为 0；原始 transport 诊断保留 `send_status=4`、`phase=4`、`usb_ready=0`、`connection_epoch=14`，transport error count 仍为 0。该结果支持预期断连分类与短回归功能，不等同于 20 轮 host-exit 验收。

健康快照原始日志分别为 `build/continuation_20261010/health008_before_exit.stdout.log`（SHA-256 `9464b2d16ed5b95144237da4663e6310b6525bba1a30d91b8e11d8f6fb14c56e`）和 `build/continuation_20261010/health008_after_one.stdout.log`（SHA-256 `5c672f2a5a5d6b1132dc0fb8abab30491e7502bb869af28e5316dd02484abde8`）。

后续 host-exit 扩展批次已在第 3 轮失败：20 轮目标中前 2 轮通过，第 3 轮 recovery receiver 以 exit 1 结束。stderr 显示握手读取 control response 超时；根代理正在核查现场与 health，当前不能把失败归因于单一固件原因。批次证据位于 `report/g7_runs/g7_batch_receiver_exit_20261010_183956_107_2a94b9ed`，`batch_summary.json` SHA-256 `3acfc7d12b99c18db66870cd1e5d9acf406dff7ee9143dbb7a28c07126cb6272`；第三轮 stderr SHA-256 `37bf51f9ebb99d9319aec90ed08e7608a8b8260fc2ebafd7aefee8ba68809e14`。失败后的 health 与清零读回单独记录如下；这些结果没有把失败轮次变成通过。历史 006d 累积的 host-exit health/transport 问题不被本次单轮覆盖或抹去。

失败后现场快照显示 `status=1`、fatal/control/transport counters 均为 0，但原始 transport 诊断仍为 `send_status=4`、`resume_status=0`、`usb_ready=0`、`connection_epoch=24`、`last_successful_frame_id=4`、transport error count 0。日志 `build/continuation_20261010/health008_after_failure_retry.stdout.log` SHA-256 `b0d376157c466a081d47645821824888e8f5a991b8a1fc8bdeab8a4b3c715fdc`。同一现场的 cleanup 读回日志 `build/continuation_20261010/cleanup008_after_failure.stdout.log` SHA-256 `269225c236bedc4a9c6fc938871ace457e8dda9bb95e87fd13d3039aed165f4a`，再次报告 135,168 B 三个 DDR 对象全零、stage 6/result 0。此清理成功不能替代握手/receiver 恢复通过；控制响应超时仍是失败。

另一项未重载 JTAG 的 bad-Finished/REKEY 场景中，bad Finished 被拒绝且首个会话认证视频通过（140 帧，约 47.453 fps）；随后 REKEY 的第二次 HELLO_ACK 等待 control response 超时，整项结果为 failed，因此不能称为双会话通过。脱敏结果 `data/captures/g6_usb_20261010_184555_821078/result.json` SHA-256 `cebc4f8cfa170de9d8fcb662b8acc439167597eed14bb6417b7644f83b7ac1e6`。其中参数确认未重新 JTAG 加载；session ID 与 transcript 指纹未复制到本报告。

该 REKEY timeout 后的 health 快照为 `status=2`、fatal=1、control=1、transport=0，raw `send_status=4`、`resume_status=0`、phase=4、`usb_ready=0`、epoch=24、last frame=140。日志 `build/continuation_20261010/health008_after_rekey_timeout.stdout.log` SHA-256 `c3b71a20bcf30f4cadbe5c5b6ae4390d6bc46b0b9d0c7a874b4d85ad2009e1e4`。bad Finished rejection 是此场景的预期检查之一，可能贡献 fatal/control 各一次；因此这些总计数不能单独归因于 REKEY。对应 cleanup 读回日志 `build/continuation_20261010/cleanup008_after_rekey_timeout.stdout.log` SHA-256 `269225c236bedc4a9c6fc938871ace457e8dda9bb95e87fd13d3039aed165f4a`，显示 named DDR ranges 全零；它与失败后另一份 cleanup 日志字节相同，且 close 后诊断可能覆盖此前状态，不能据此判定 HELLO_ACK 超时发生时或其直接路径的 buffer 状态。

## 离线与 canonical 兼容验证

本轮电脑端回归通过：实际共享清理头文件的 C harness；`sim.tb.test_g6_auto_recovery` 9/9；USB bounded SDK/mock 3 项；control-dispatch C harness。harness 覆盖 cleanup 顺序、DMA/USB busy 与错误门禁、全容量 wipe/readback、USB FLUSH/PRIME 失败时不提前擦除或重建，以及 disconnect 分类。

可复现入口（仓库 `.venv`）：

```powershell
.venv/Scripts/python.exe -c "from sim.tb.test_g6_secure_cleanup import test_g6_secure_cleanup_real_header_harness; test_g6_secure_cleanup_real_header_harness()"
.venv/Scripts/python.exe -m unittest sim.tb.test_g6_auto_recovery -v
.venv/Scripts/python.exe -c "from sim.tb.test_usb_bounded_sdk import test_hash_pinned_patch_and_ch9_failure_routing, test_register_mock_compiles_and_runs_when_native_gcc_exists, test_generated_intr_and_cdc_class_execute_with_host_stubs; test_hash_pinned_patch_and_ch9_failure_routing(); test_register_mock_compiles_and_runs_when_native_gcc_exists(); test_generated_intr_and_cdc_class_execute_with_host_stubs()"
.venv/Scripts/python.exe -c "from sim.tb.test_g6_control_dispatch import test_g6_control_dispatch_real_header_harness; test_g6_control_dispatch_real_header_harness()"
```

普通 canonical G6（未定义 `G6_SECURE_CLEANUP`）曾以手工 ARM compile/link 验证通过，ELF 位于 `build/vitis/canonical_g6_compat_20261010/obj/g6_canonical_compat.elf`，SHA-256 `9280fba70112616c018364bf4753d9e3ac775cee0211467aa597253643768a49`。这只是普通 G6 源的手工编译/链接兼容检查，**不是** `prj/build_g4.py` 官方 Vitis launcher 全流程；该 launcher 在当前 Python 环境无法导入 `vitis`。

## 历史候选与限制

早期 cleanup prototype 曾构建失败，但其失败输出目录/log 后来被删除，现无法复核原始失败日志。随后生成的旧 `candidate008` 成功构建目录未上板；本次有实板 STOP 与 DDR 读回证据的是 `candidate008_retry1`，两者身份不可混用。retry1 上出现的 receiver-exit 20 轮批次仅 2/20 通过，以及 REKEY 第二次 HELLO_ACK 超时，均应保留为失败证据。retry1 源身份固定后若再修改任何纳入 manifest 的源码，应新建 retry 目录并重建，不得沿用本 ELF 的读回结论。

本轮没有实现或验证可信熵源、provisioning、密钥隔离/轮换/销毁，也没有擦除长期 private key、seed 或防重放 transcript 状态。PL/GCM 内部全域清零、DMA/USB 以外内存、掉电/硬复位行为与生产威胁模型仍未通过；candidate008 仅是有限范围的清理实现和实板功能/对象读回证据。
