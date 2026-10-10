# USB EP1 IN 所有权门禁审阅

日期：2026-10-10。本文只审阅 candidate008_retry1 与其 pinned USBPS SDK，不修改源码。结论限定在设备模式 EP1 IN、TX ring/descriptor 清理路径。

## 结论

candidate008_retry1 在 TX 清理前检查了 `ENDPTFLUSH` 对应位清零和 `ENDPTPRIME` 对应位清零，但没有读取 `ENDPTSTAT`。AMD Zynq-7000 UG585 的 de-prime 流程明确要求：FLUSH 清零后再检查 ENDPTSTAT；若被 flush 的端点仍为 active，表示 flush 可能因传输中的 packet 被拒绝。因而 candidate008 的 135,168 B DDR 全零读回证明了指定地址在采样时为零，不能证明 USB 控制器在清理前已经完全放弃该 buffer 的所有权。

寄存器名要区分：本项目 BSP 的 `XUSBPS_EPSTAT_OFFSET` 是 `ENDPTSETUPSTAT`，偏移 `0x1AC`；`XUSBPS_EPRDY_OFFSET` 位于 `0x1B8`，是 UG585 中的 `ENDPTSTAT`。EP1 IN active mask 为 bit 17。UG585 还说明 prime 完成时 PRIME 位清零且 STATUS 位为 1；这和 flush 后要求 STATUS 位为 0 是不同判据。[AMD UG585：Flushing/De-priming an Endpoint](https://docs.amd.com/r/en-US/ug585-zynq-7000-SoC-TRM/Example-Flushing/De-priming-an-Endpoint)；[AMD UG585：Data Phase](https://docs.amd.com/r/en-US/ug585-zynq-7000-SoC-TRM/Data-Phase)。

## 对 candidate008 的源码核对

`src/ps/diag/usb_bounded_sdk_policy.h::XUsbPs_BoundedQuiesceEndpointWithLimit` 当前顺序是写 FLUSH、bounded poll FLUSH=0、bounded poll PRIME=0、最后调用 `XUsbPs_EpDisable`。gate 不读取 `XUSBPS_EPRDY_OFFSET`。`prj/usb_probe_auto_recovery.c::secure_tx_quiesce` 只记录 flush/prime status 与 poll 数，成功后 `secure_tx_wipe` 才清 USB TX buffer；`secure_tx_rebuild` 随后清 EP1 IN EPCOMPL、调用 `eye_usb_rebuild_direction`，并恢复 endpoint enable。现有停止诊断没有记录 EPRDY，因此它不能补出缺少的端点 inactive 证据。

descriptor rebuild 本身不宜直接删除。pinned SDK 的 `XUsbPs_IntrHandleTX` 通过 EPCOMPL 事件推进软件 `dTDTail`；candidate cleanup 在 IRQ masked 状态下 W1C 清除旧 completion，再重建 endpoint。`XUsbPs_ReconfigureEp` 会重置 `dTDHead/dTDTail` 并重建 QH/dTD 队列。若丢弃 completion 但不运行等价 SDK bookkeeping，也不重建 ring，下一次 send 可能使用软件滞后的 descriptor cursor。pinned SDK 中重建函数未显式写 TXR toggle-reset 位，candidate DTR rearm 传入 `reset_toggle=0`；源码层面没有发现它主动复位 DATA toggle 的调用，但实际 REKEY 握手仍需板测验证。

## 后续实现建议

candidate009 先只加诊断，不改变008门禁行为：在原有 bounded quiesce 的 FLUSH 前、FLUSH 清零后、PRIME 清零后、disable 后记录 EP1 IN 的 EPRDY bit 17 和 EPCR1 的 TXE/TXR 相关读值；不能把诊断字段为零自动称为完整安全通过。当前实板 cleanup 日志里 FLUSH/PRIME 各只轮询一次，故额外状态采样成本可单独观察。

candidate010 再改安全门禁：保存并恢复原 CPSR IRQ mask；先 disable EP1 IN，执行 DSB/readback，再写对应 FLUSH 位；bounded poll FLUSH 清零、PRIME 清零以及 EPRDY bit 17 清零。UG585 指出 flush 后 status 仍 active 时可重复 de-prime；实现可选择在总上限内重试，或第一次超限即 fail-closed，但不得在任何一次 EPRDY 仍为 1 时 wipe/rebuild。所有 gate 成功后，才 W1C 清 bit 17、重建 IN ring、按 configured&&DTR 恢复 TXE；清理路径不得触发 TXR toggle reset。失败时保留 tx 与 descriptor bytes、保持 endpoint quarantine/sticky fault，等待已有 reset/恢复门禁。

同一 ownership 检查需覆盖 `eye_usb_rearm_data`：它在 DTR/SET_CONFIGURATION 期间会 flush/rebuild EP1 OUT、EP1 IN、EP2 IN，分别核对 EPRDY bits 1、17、18，再清相应 completion 与 QH/dTD。EP0 control、EP1 OUT 的 HELLO 消息和 endpoint toggle 只能按现有事件边界管理，不可通过清全局 completion 或随意复位 toggle 来绕开问题。

建议为真实共享 helper/header 增加可执行 host C harness，至少覆盖：

| 场景 | 注入状态 | 必须断言 |
|---|---|---|
| EPSTATUS stuck active | FLUSH=0、PRIME=0、EPRDY bit17 持续为 1 | 到达有界上限后失败；tx、dTD、QH 不被 wipe/rebuild；IN 保持 disabled/quarantined |
| late clear | FLUSH/PRIME 清零后 EPRDY 在有限轮询后清零 | 只在 inactive 读回后允许后续 cleanup |
| flush retry | 第一次 FLUSH 完成但 EPRDY 仍 active，下一轮 de-prime 后转 inactive | 按单一总预算重试且仅 inactive 后清理；超过预算则不写共享对象 |
| 顺序审计 | 记录 MMIO 与 descriptor 回调顺序 | disable < FLUSH < FLUSH/PRIME/ENDPTSTAT gates < W1C completion < rebuild < enable |
| 保持 completion/toggle 边界 | 其他 EPCOMPL 位与 OUT/EP0 状态置位；EPCR1 TXR 初始状态保留 | 只 W1C bit17；不置 TXR reset；成功重建后 IN queue cursor 合法 |
| 正常连续 send/rekey | 连续完成两次 IN send，再进入 REKEY/HELLO_ACK send | 软件 dTD ring cursor、`tx_ready` 和主机 DATA toggle 语义连续；协议回应通过 |

以上是建议的候选方案与离线验收矩阵，不表示 candidate008 已有 ENDPTSTAT gate、candidate009/010 已实现，或当前 REKEY timeout 已被定位。candidate008 的实板 DDR OR=0 与 receiver/REKEY 超时是两个独立观察；清零读回不可替代 USB endpoint ownership 证明。
