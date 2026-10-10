# candidate006d ReceiverExit 单轮与板端健康计数

整理：2026-10-10。本文只记录同构建 `candidate006d` 的一轮主机接收进程退出恢复，以及该轮前后的只读板端健康快照。没有进行第二轮、构建、固件修改或额外硬件操作。

## 结果分层

主机自动化 runner 的 `trial_01_try01` 判据通过：终止旧接收进程前观测到至少 2 帧认证并解码的视频；新进程没有 JTAG 重载，完成新会话和密钥指纹，收到 94 帧、755 个认证视频包，主机侧错误计数为零。该结果是 **ReceiverExit 主机恢复 1/1 通过**，不是 20 轮验收。

独立的前后板端快照显示 `status` 从 1 到 3、`fatal` 从 0 到 2、`transport` 从 0 到 2，`control` 保持 0。也就是说，主机恢复结果通过的同时，板端 clean-health 没有保持零增量。runner 的 summary 按主机恢复判据标记 `passed`，它没有把板端快照作为本场景的门槛；不能据此写成板端无错误或整项 G7 通过。

| 观测 | 基线 | 单轮后 | 增量/含义 |
|---|---:|---:|---|
| G6 status | 1 | 3 | +2；`fail_closed()` 每次调用都会加一 |
| fatal | 0 | 2 | +2；与两次 `fail_closed()` 对应 |
| control | 0 | 0 | +0 |
| transport | 0 | 2 | +2；视频发送失败计数 |
| transport failure snapshot | 未记录失败（`send_status=0`, `resume_status=0`, `transport_error_count=0`；`last_successful_frame_id=141`） | `send_status=4`, `resume_status=0`, `phase=4`, `usb_ready=0`, `connection_epoch=14`, `last_successful_frame_id=94`, `transport_error_count=2` | 最近一次记录显示发送失败时处于 STREAM，USB 未 ready；DMA resume 返回值为 0 |

原始只读快照：[运行前](../build/g7_receiver_006d_20261010/health_before.stdout.log)、[运行后](../build/g7_receiver_006d_20261010/health_after_one.stdout.log)。原始单轮记录：[batch summary](../build/restoration_source_b83ee4e/report/g7_runs/g7_batch_receiver_exit_20261010_133117_645_eb93e74b/batch_summary.json)、[trial JSON](../build/restoration_source_b83ee4e/report/g7_runs/g7_batch_receiver_exit_20261010_133117_645_eb93e74b/trial_01_try01.json)（源 JSON 含 session ID、密钥指纹和本机绝对路径；本文未复述这些字段）。不含这些敏感字段、记录原始文件相对路径与 SHA-256 的机器摘要见[脱敏 JSON](g7_receiver_exit_006d_board_health_20261010.json)。

构建身份与本轮记录相同：manifest SHA-256 `0eb922b903f4f87b555a09cce67e928d5a910a37ece3ba359aebe055ffe28abc`，ELF SHA-256 `e93ad4b6551bb993821a8e396d8f4c4c1f40c6bd6292247391ff129a0d9e8051`，XSA SHA-256 `46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`。trial 中旧会话和恢复会话的 ID、密钥指纹不同，`jtag_reload=false`。

## 源码能解释的行为

在冻结源码中，`send_frame()` 把 `usb_cdc_send()` 非零返回映射为状态码 4；主循环在 `g3_usb_resume()` 返回 0 但发送失败时，递增 transport 计数并调用 `fail_closed()`。[发送路径与错误计数](../build/restoration_source_b83ee4e/src/ps/src/g6_usb.c#L135) [USB 发送返回条件](../build/restoration_source_b83ee4e/prj/usb_probe.c#L340) 因此这里的 `send_status=4` 是 `send_frame()` 的包装状态，不是 `usb_cdc_send()` 的底层返回码，不能据此区分 endpoint 发送失败、ready 丢失或 connection epoch 改变。

`fail_closed()` 会清 PL GCM 会话、将 phase 设为 FAULT，并递增 fatal 与 status；发送失败分支先递增 transport，再调用它。[fail_closed 与计数路径](../build/restoration_source_b83ee4e/src/ps/src/g6_usb.c#L82) 随后主循环若观察到 connection epoch 变化，会清理旧会话并把 phase 置回 `WAIT_HELLO`；USB CDC 在配置/DTR 状态变化时会推进 epoch，发送调用也会检查 ready 和 epoch。[epoch 重置与 FAULT 分支](../build/restoration_source_b83ee4e/src/ps/src/g6_usb.c#L186) [USB CDC epoch 与发送](../build/restoration_source_b83ee4e/prj/usb_probe.c#L102) 这解释了为什么即使发生 fail-closed，新的 USB 连接仍可完成新握手；fatal/status 计数不会因新握手而清零。源码表明 DTR 状态变化可以推进 epoch，但本轮没有直接观测到主机是否实际发送了 DTR deassert。

诊断结构头文件把 transport snapshot 注释为“first transport failure”，但生成的固件代码在每次发送失败时都写入该结构，并把累计值写入 `transport_error_count`。[诊断结构](../build/restoration_source_b83ee4e/src/ps/include/g6_auto_recovery.h#L61) [固件生成的写入点](../build/restoration_source_b83ee4e/prj/build_g6_auto_recovery.py#L46) 当前 `transport_error_count=2` 与 transport 增量一致；其他 snapshot 字段只能代表最后一次写入，不能还原两次事件的先后或逐次原因。`phase=4` 是该诊断写入时的 phase（枚举中 STREAM 为 4），并非快照读取时确认的实时 phase。[phase 枚举](../build/restoration_source_b83ee4e/src/ps/src/g6_usb.c#L57)

旧 reader 被强制终止会关闭其 CDC 句柄；短时恢复 reader 结束时也会关闭句柄。基于 `usb_ready=0`、连接 epoch 与最近成功帧编号，两个进程生命周期中的断连发送失败是与源码和快照相符的解释，但当前快照没有每次事件的时间戳，无法把两次增量分别、确定地归因到哪次关闭，也没有单独记录操作系统是否实际发送了 DTR deassert。这里应写“与预期 USB 断连相符”，不能写成已证实的两次 DTR 事件。

## 验收裁定与后续实现决定

当前证据支持两个并列结论：

- **主机 ReceiverExit 恢复：1/1 通过。** 认证视频在旧进程结束后通过新进程、新会话恢复，且无 JTAG 重载。
- **板端零增量健康：本轮未满足。** 观察到 2 次 transport/fatal/status 增量；无法仅凭汇总快照证明这些增量全部属于应豁免的预期 DTR 断连。

root 已决定按新固件修复路径处理，不追认或豁免 006d 的两次错误：在新 candidate008 中，只有发送失败时观测到 `usb_ready` 已下降或 connection epoch 已变化，并且 `secure_cleanup` 有成功证据，才分类为预期 disconnect；原始 failure diagnosis 仍保留。若 `usb_ready=1` 且 epoch 未变化仍发送失败，或 cleanup 未成功，仍按 fatal/transport 错误处理。该规则尚在 candidate008 集成阶段，未构建、未实测，不能记作通过。

在后续恢复操作中，root 只读快照显示板卡重新加载已验收冻结 006d 后健康计数为 `status=1 fatal=0 control=0 transport=0`（[恢复后快照](../build/continuation_20261010/health_restored.stdout.log)）。这只是重新加载后的独立状态，不能并入、清零或抵消上文 host-exit 批次的 `+2` 计数。

因此，006d 本轮不得计入“板端 clean-health 通过”，也不计入新固件门禁；原批次失败事实保留。candidate008 完成集成后，需以新身份独立运行 receiver-exit 20 轮，逐轮留存 USB ready/epoch 变化、`secure_cleanup` 成功证据、原始 failure diagnosis、新会话与认证视频及无 JTAG reload。任何 `ready=1` 且 epoch 不变时的发送失败，或 cleanup 失败，仍为 fatal/transport 错误并按失败即停处理。物理 USB 拔插门禁仍在该 receiver-exit 门禁完成后进行；未实测前不把预期断连分类写成安全或恢复通过。
