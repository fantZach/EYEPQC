# 下一阶段执行计划

更新：2026-10-10。用户本轮明确先做隔离 Keccak 板测和安全/交付准备；已按该顺序完成无需物理配合的工作。G0/G7 的剩余门禁仍独立保留，不因这次顺序调整视作通过。已有证据见 [验收矩阵](acceptance_matrix_20261009.md)，历史过程保留在 [progress](progress.md)。

USB EP0 所有权修复已完成。最终 candidate006d/v4 的短时认证视频、camera-reset 20/20、routing-stall 20/20 通过；180 项 manifest 检查与逐轮同构建审核通过。详情见 [006d 报告](g7_candidate006d_acceptance_20261010.md)。同构建 PC receiver-exit 已完成 1 轮：主机恢复判据 1/1 通过，但板端 `status/fatal/transport` 各增加 2，`control` 不变；该批次未达到 clean-health，不能计作通过或用后续重载清零。root 已决定在 candidate008 中实现预期断连分类：仅当 `usb_ready` 下降或 connection epoch 变化，且有 `secure_cleanup` 成功证据时才分类为预期 disconnect，并保留原始 failure diagnosis；ready=1 且 epoch 不变时的发送失败或 cleanup 失败仍按 fatal/transport 错误处理。candidate008 尚在集成、未验证；完成后需新构建独立跑满 receiver-exit 20 轮。详见[006d receiver-exit 板端快照报告](g7_receiver_exit_006d_board_health_20261010.md)。旧 usbfix3 的通过批次不代替最终候选。

| 顺序 | 任务与交付 | 前置条件/完成判据 | 用户介入 |
|---|---|---|---|
| 0 | GitHub 上传 | 权限环境恢复后，19 文件提交 556a659 已非强制推送成功；后续板测与交付记录继续单独提交 | 无需动作 |
| 1 | candidate008 同构建 PC 退出/DTR 20 次 | 先完成固件分类与成功 `secure_cleanup` 证据集成并生成新构建；仅 `usb_ready` 下降或 epoch 变化且 cleanup 成功时分类为预期 disconnect，保留原始诊断。`ready=1` 且 epoch 不变的发送失败或 cleanup 失败仍为 fatal/transport 错误。之后独立新批次跑满 20 轮：唯一 reader、逐轮同构建、故障前后认证流与新 HELLO/session/key/认证帧、ready/epoch/cleanup/计数及无 JTAG 重载留证；失败即停、保留批次。旧 006d 的两次计数不豁免、不并入新批次 | 通常不需要；设备接线或供电异常时才提示 |
| 2 | candidate008 同构建物理 USB 拔插 20 次 | 第 1 项通过后逐轮提示；确认拔线时接收进程存活且认证流活动，PnP 断开/返回、新握手与认证帧，无恢复 JTAG 下载；独立记录 ready/epoch、cleanup 与原始 failure diagnosis，不以预期断连分类替代恢复判据 | 需要按提示拔插 USB Slave 数据线，保留 JTAG 和板卡供电 |
| 3 | G0 SD 独立启动、物理复位和 30 分钟冷启动 | 使用匹配 final2 BOOT.BIN/XSA/manifest 与专用 SD；按 G0 现场流程采集启动、一次物理复位、全断电上电后的 1800 秒日志 | 需要读卡器、可用于项目的专用 SD 卡及拨码/复位/上电操作。当前没有读卡器，板上原卡保持原样 |
| 4 | M02 摄像头现场补项 | 独立记录 20 次冷启动、未插/错误接线退出等原判据；与 G0 单次及 30 分钟门禁分开，不把受控 PL reset 当物理拔除 | 需要配合摄像头接线与冷启动；安排时给具体步骤 |
| 5 | Keccak 实板功能已验证，优化搬运后再评估收益 | 按用户本轮授权提前测试独立 route4k：修复非法 MMIO 读取和 UART 打印 ABI 后，SW 1 轮/HW 3 轮通过 KAT、ID、96 次硬件调用与 timeout fallback，STATUS 清理通过。初版完整解封装 HW 约慢 8.6%；身份核验移至 configure 的新版三次启动逐次 KAT/96 dispatch 通过，但仍慢约 8.4%，暂不集成正式视频。全域寄存器清零读回仍未证明。后续评估保留 sponge 状态/减少搬运的接口方案，再新构建实测 | 无需当前动作；新板测保持唯一执行者 |
| 6 | CPU 临时协议缓冲清理已实现，生产硬件/产品门禁待闭环 | candidate007 控制 helper harness、183 项预检与实板双会话/坏 Finished 回归通过；完整清零仍未证明。确定可信熵、密钥 provisioning/存储和 PS/cache/DDR/PL/USB 的清零边界，实现并取得读回/失败场景证据；JTAG 开发注入不等于生产安全 | 需要安全目标/部署条件信息时再集中询问 |
| 7 | 脱敏源码/证据审阅包已准备，正式比赛定稿待规则 | 按最终构建整理吞吐、窗口、延迟、错误计数、资源和原始证据索引；现有 15 秒 722 帧录像不外推长录可靠性。规则明确后制作指定论文/PPT/视频/附件 | 提供正式比赛规则、格式和截止时间 |

本轮实际产物见 [Keccak 实板报告](keccak_board_benchmark_20261010.md)、[生产安全计划](production_security_plan_20261010.md) 和 [提交包计划](submission_delivery_plan_20261010.md)。最新只读核验时没有 CDC 枚举、JTAG probe 可见；随后 root 仅重载已验收冻结 006d，3 秒认证视频加 STOP/drain 回归通过（47.719 fps），reader 已释放。续轮恢复后的独立健康快照为 `status=1/fatal=0/control=0/transport=0`（`build/continuation_20261010/health_restored.stdout.log`）；它不并入此前 receiver-exit 失败批次，也不抵消该批次的 `+2/+2/+0/+2`。006d 同构建 20 轮未跑；candidate008 分类修复尚未验证，需新构建并独立完成 20 轮。视频原始结果：`build/restoration_source_b83ee4e/data/captures/g6_usb_20261010_181838_183430/result.json`（本计划不复制会话标识、密钥指纹或媒体内容）。

第 1 项仍是恢复验收的下一项板测任务；等待物理动作时可继续电脑端证据归档、生产安全方案和比赛材料缺口整理。本轮 Keccak 测试仅临时 JTAG，不写 SD/Flash、不改变板上原卡；结束后恢复视频固件。多代理可恢复时，根代理负责计划和审查、执行代理各负责恢复、启动交付、加速器离线准备；任何时候只有一个执行者占用板卡，避免并发 reader/JTAG。

约 50 分钟长测沿用用户既有时长例外，始终标明未实测满 2 小时。camera-reset 与 routing-stall 证明受控 PL 故障下 S2MM Busy 到约 3 秒软件 deadline 的恢复，不宣称硬件 DMA timeout IRQ 或物理传感器拔除。下一次上板前仍须重新核验设备状态，不能将本次短时回归外推至持续在线或剩余 G7 场景。

续推进证据见 [身份核验优化板测](keccak_identity_cached_20261010.md)、[CPU 清理实施记录](security_cleanup_20261010.md) 和已更新的 [技术报告稿](technical_report.md)。新候选不覆盖旧006d验收；此前恢复冻结006d并复测140帧的记录仍有效，最新 3 秒认证视频回归也已通过。receiver-exit 的实现方向已确定为 candidate008 的条件分类与 cleanup 证据，不豁免旧 006d 错误；新固件和 20 轮门禁仍待实现、验证。
