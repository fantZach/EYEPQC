# Candidate 010 USB TX 清理离线审阅

日期：2026-10-10
结论：候选 010 的离线构建和本报告列出的 host tests 通过。IRQ 状态恢复、端点 EPRDY gate、TX 全容量清理路径已由源码及 ARM ELF 核对；这些结果不能替代板端验证，也不表示生产安全验收完成。

## 范围与构建身份

审阅范围是候选 010 的 G6 USB 发送队列清理、SDK bounded quiesce policy、G3/G6 清理编排和只读诊断路径。本轮未操作板卡、JTAG、串口或 Git。

新候选独立离线构建目录为 `build/vitis/g6_secure_cleanup_20261010_candidate010_idle_fastpath_rerun`。其 variant 为 `g6-secure-buffer-cleanup-usb-bounded-candidate010-idle-fastpath-v1`；`g6_usb_manifest.json` SHA-256 为 `c064a826f74d35262a2ad830146fd7fcf43b61176fc5204e58d7651c9526b8c6`，source-baseline manifest SHA-256 为 `137a4309fbe5b3436927b5374db1fbfdcd43b55998d9b16451da9b6fcb514eee`。构建记录的 `board_validated` 为 `false`。ELF `g6_usb/build/g6_usb.elf` SHA-256 为 `4e48ba2b0d9690f72d602d0dc1087a644f137189400bcf4ae9beb2dade5d0ff6`；map SHA-256 为 `1edba56ea9965cdc9396a0924950fd0e07d0f89b3e42bb99930687b85bccd029`。

主要源文件和 harness 的 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `src/ps/src/g3_camera.c` | `57458e1ea00fc2350cc8b143e078e5097be39aed6a402a39284f5e4a150c8ed1` |
| `src/ps/src/g6_usb.c` | `f6ffe9e101c3f46b0c8b73f2b8b5b9112e00bf5417fc1a66d626cad7c2c85c26` |
| `src/ps/diag/g3_camera_auto_recovery.c` | `60a8ce06c07e9d5ffcd08573908fccb0c70c7dd902475a56ee5fd829c8cc9ca2` |
| `src/ps/diag/usb_bounded_sdk_policy.h` | `fcc672247be4cabacd1d398faf872d57cb02a62f1780566ce7532e9ac2e96f4d` |
| `src/ps/include/usb_recovery.h` | `8360d1b95973c8e26a1e1862f2da4fc3a171e2d08d902e585e5a37da896eaa50` |
| `src/ps/include/g6_secure_cleanup.h` | `7fb6f0da4fc84a6f62907e58cf2c95c71f40874fa9cbcb76b2e664b95c000434` |
| `prj/usb_probe_auto_recovery.c` | `0cfeefb4979171ce0b4e437ae082cefbb2c84b8a456dadf81988068b6337efcf` |
| `sim/tb/test_g6_usb_idle_fastpath.c` | `349919a617301ef0f7b78e168f803a46dcaef2f854e034f23a5eecdcf210f7ea` |

其 Python runner `sim/tb/test_g6_usb_idle_fastpath.py` 的 SHA-256 为 `8d6078267c5424bd6496a37a57c88645075ffe9de335b278a1d3a4debc001061`。固件 source hash 与候选 manifest 中的 source hash 相符；harness hash 用于固定本次离线测试输入。

## 清理顺序与所有权门禁

`secure_tx_cleanup()` 先保存 CPSR 并屏蔽 IRQ，在同一临界区中执行 ring 检查、idle wipe 或 slow quiesce/wipe/rebuild，所有分支最终经过一次恢复路径。代码只依据保存 CPSR 的 I 位选择 `cpsid i` 或 `cpsie i`，因此保留进入函数前 IRQ mask 状态；未声称恢复或改写整个 CPSR。对实际候选 ELF 的 `usb_cdc_secure_cleanup_tx` 反汇编确认了 `mrs r9, CPSR`、`cpsid i`，随后检查 `r9 & 0x80` 并在离开前走 `cpsid i`/`cpsie i` 分支。该证据是本地候选 ELF 的静态反汇编，不是板端时序测量。

idle 快路径只清 TX CPU 缓冲，不重建或修改 endpoint ring。它先要求 TX buffer 非空、容量严格等于 1472 字节且 64-byte 对齐；EP1 IN ring 为四项且 QH、dTD 数组、head/tail 均存在；head 和 tail 属于四项 ring；每个 dTD 的 next link 指向环内下一项。结构错误返回失败路径，不能进入 slow rebuild。结构成立但连接未配置、DTR 未置位、TX 未 ready、head/tail 不同或 descriptor/QH token 含 ACTIVE/HALT/XERR/BUFERR 时，只允许进入 slow path；硬件 FLUSH、PRIME、EPRDY、completion 必须均 inactive/clear，EP1 TXE 必须打开且 endpoint fault 未置位，才允许走 idle wipe。

slow path 的顺序是保存 IRQ 状态并屏蔽 IRQ、EP1 IN disable、DSB、读取 EPCR 确认 TXE 已关、bounded FLUSH 清零、bounded PRIME 清零、读取 EPRDY/ENDPTSTAT 确认 inactive；若 EPRDY 仍 active，则重新 FLUSH，并在同一 poll budget 内重试。任一门禁失败会停在 fail-closed 路径，不清 completion、不擦 TX、不重建 ring。quiesce 成功后才清完整 TX 容量并读回 zero-or，之后才 W1C 对应 IN completion 并确认其清零，再重建。idle 快路径只接受 completion 已为零的状态，不会提前清 completion。恢复 helper 对 EP1 OUT、EP1 IN、EP2 IN 也先分别通过 disable/readback、FLUSH/PRIME/EPRDY，再统一清对应 completion 并重建；任一方向失败时不进行 completion 写或 descriptor 重建。

poll limit 为 256。三个状态类分别共享自己的总预算，包含 reflush 重试；因此单方向每类读取不超过 256 次。CPSR IRQ 屏蔽段包含这段有界寄存器轮询，源代码没有无限等待。实际中断延迟仍需板端观测。

TX 清理依次 invalidate cache、对 1472 字节写零、flush cache、DSB、invalidate，再逐字节 zero-or 读回并写入诊断。native harness 对整段 TX 缓冲检查全零和 `tx_zero_or == 0`；ARM ELF 中可见对应 cache 调用、DSB、全范围字节写循环和 readback 路径。该 host 检查中 cache API 是 stub，不证明真实 cache/DDR 一致性。

G3 cleanup orchestration 顺序是 reset/停 DMA 并清 GCM，清理完整 `g3_frame`、`g3_sealed`，最后 quiesce/wipe/rebuild TX；任何阶段失败会停止后续步骤并转 FAULT。DMA gate 要求 reset 成功，capture RX、crypto RX、crypto TX channel status 中无 `XAXIDMA_ERR_ALL_MASK | XAXIDMA_IRQ_ERROR_MASK` 且有 HALTED 或 IDLE；GCM status bits clear 后才能擦 frame/sealed。frame 和 sealed 清理使用全容量 wipe、cache maintenance 和 zero-or readback。当前离线 header harness以已核实的 DMA error-bit 值覆盖各错误位与三个 channel；真实 `g3_camera.c` 使用 BSP 宏。离线 harness 的 DMA/GCM 操作是 fake callback，并非真实 DMA 停止读回。

## 离线验证

以下命令在项目 `.venv` 和本机 MinGW GCC 环境运行，均通过：

| 命令 | 结果 |
|---|---|
| `.venv/Scripts/python.exe sim/tb/test_usb_bounded_sdk.py` | `USB_BOUNDED_SDK_TESTS_PASS 3/3`，包括 SDK patch、寄存器 mock、generated EP0/interrupt/CDC/Chapter 9 host harness |
| `.venv/Scripts/python.exe -m unittest sim.tb.test_usb_recovery` | Python `1/1 OK`；真实 recovery header C harness 内部 `8/8 PASS`，覆盖 stuck FLUSH、PRIME、EPRDY、disable readback failure、late EPRDY clear/reflush 和不早清 completion |
| `.venv/Scripts/python.exe -m unittest sim.tb.test_g6_usb_idle_fastpath` | `1/1 OK`；编译并调用实际 probe cleanup 函数与候选 009 pinned SDK 类型，覆盖 healthy idle wipe、active fallback、无效 head/tail、错误 ring count、QH/descriptor 错误位和 endpoint fault |
| `.venv/Scripts/python.exe -m unittest sim.tb.test_g6_auto_recovery` | `9/9 OK`，保持已有 recovery 状态和入口断言 |
| `.venv/Scripts/python.exe -m unittest sim.tb.test_g6_cleanup_paths` | `1/1 OK`，使用 G6 源码分支 harness 检查 STOP/REKEY/fail-closed 编排和长期材料语义 |
| `.venv/Scripts/python.exe -c "from sim.tb.test_g6_secure_cleanup import test_g6_secure_cleanup_real_header_harness; test_g6_secure_cleanup_real_header_harness()"` | real-header C harness 通过；覆盖三 DMA channel 的 `ERR_ALL`/IRQ error 位拒绝、HALTED/IDLE 门禁、GCM status、阶段顺序、frame/sealed/TX 全容量 guard wipe 和 USB ownership predicate |
| `.venv/Scripts/python.exe -m unittest sim.tb.test_read_g6_secure_cleanup_tcl` | `6/6 OK`，仅验证只读 reader 的静态结构/输出字段约束 |

另外，候选 ARM ELF 中 `usb_cdc_secure_cleanup_tx` 静态反汇编能看到 CPSR IRQ mask 保存与恢复分支；`secure_tx_wipe`/`secure_tx_quiesce` 存在 cache、DSB 与有限轮询代码。没有运行 JTAG/Tcl 读回。

## 未覆盖与生产边界

- 没有 candidate010 板端测试；构建 manifest 明确 `board_validated=false`。candidate008/009 的旧板测记录不证明本候选行为，也不证明此处完整清零。
- idle harness 会破坏性测试 head/tail、数量、QH token 等结构门禁，但未显式篡改 `dTDs` base 或某项 NLP next link。源码包含 NLP 链接检查；仍需增加这两种 malformed ring 的失败用例。`dTDs` 目前只有非空/count 检查，尚无独立可信的 descriptor-pool base/capacity 可用于在解引用前证明数组本身位于已知对象范围。
- CPSR 顺序已检查候选 ELF；host mock 无法执行 ARM IRQ 语义。尚无板端 IRQ 延迟测量。
- frame/sealed/DMA/GCM 的 offline harness 覆盖共享 helper 和假 callbacks；没有对真实 DDR 区域、DMA reset 后硬件 status 或 GCM register 做 candidate010 物理读回。
- USB `EPRDY` 与 queue ownership 只用本机 register mocks 和候选 SDK 类型验证；实际 EPCR/ENDPTSTAT 时序、host DATA toggle、连续会话/REKEY、物理拔插及 DTR 竞争尚未由 candidate010 板测覆盖。
- 私钥、长期 seed、寄存器内部态、cache/DDR coherence、硬复位后残留和其他未枚举 RAM 区域不在此 TX 清理证明范围内。零化结果只涉及代码明确列出的对象容量。

因此当前状态是：010 离线构建与针对性 host 测试通过；生产安全验收和 candidate010 板端清零验收仍未通过。
