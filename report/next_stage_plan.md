# 下一阶段执行计划

更新：2026-10-11。M02 Explore 候选静态时序门禁、RTL 仿真 4/4、同会话传感器复位/配置 20/20、20 次整板断电/上电后 JTAG 配置 20/20，以及无模组 fail-closed 均通过；探针不代表 SD/Flash 独立启动或 DVP/JPEG 采集。KX41 新候选 software/hardware/timeout fallback 三窗口全 60 组实板 KAT 通过，硬件窗口耗时为软件的 88.6%。G7 candidate012 的 ownership 诊断构建通过离线预检、dry-run 和短时认证视频基线；receiver-exit 恢复时电脑仍读到 0 字节，但板端确认新 HELLO_ACK 的 IN dTD 完成（51/51 字节、零残余、所有身份匹配标志通过）。这缩小了问题范围，仍未证明 Windows CDC 应用层收到 ACK，根因未确认。SDK 源码检查未发现 `XUsbPs_ReconfigureEp(..., DirectionChanged=0)` 改写 EPCR toggle reset 位；DTR 恢复路径也不请求 toggle reset。未运行 G7 20 轮或物理 USB 拔插批次。G0/G7 剩余门禁独立保留，不因顺序调整视作通过。M02 逐轮证据见 [M02 实板报告](m02_sensor_reset_board_20261011.md)；G7 证据见 [candidate011 实板报告](g7_candidate011_receiver_exit_board_20261011.md) 和 [candidate012 ownership 诊断报告](g7_candidate012_tx_ownership_board_20261011.md)。

## 本轮续推进（2026-10-11）

M02 默认实现曾以 WNS `-0.052 ns` 失败。相同 RTL/XDC 使用 `Explore` 与 `AggressiveExplore` 后均通过最终静态时序门禁，WNS `+0.017 ns`、WHS `+0.041 ns`、DRC 0 项；余量较小，AggressiveExplore 未进一步改善。固定 Explore bit/XSA/PS7 init hash 和复现实验见 [M02 构建报告](m02_timing_explore_20261011.md)。`sim/tb/test_m02.py` 重新运行 4/4 通过；探针支持 `-SensorResets 1` 和严格的 `-ExpectCameraFailure` 负向门禁。

KX41 采集器的完成标记已修正为固件实际输出 `KX41_BENCH_DONE`；13 项 parser/runner 测试通过。候选 `build/kx41_capturefix2_20261011` 的 `--verify-only` 复核 715 项哈希通过，ELF/XSA hash 和 WNS `+0.029 ns`/WHS `+0.082 ns` 匹配。新的 10.157 秒实板采集三窗口各有 60 个唯一 KAT 通过，硬件窗口回退为零；日志 SHA-256 为 `458059e8bb7e01a3953e9cb8e9c3dda983e0a4f8b066eae72ff23bc703bbc525`。旧错标记试跑保留为 runner 缺陷记录，不合并进验收。M02 同板完成 20 次传感器 reset/config probe（20/20，sensor ID `0x5640`、error=0），但未进行整板断电循环。详见 [KX41 实板报告](keccak_sponge_x4_capture_fix_20261011.md)、[机器记录](keccak_sponge_x4_capture_fix_20261011.json) 和 [M02 实板探针报告](m02_sensor_reset_board_20261011.md)。

USB EP0 所有权修复已完成。最终 candidate006d/v4 的短时认证视频、camera-reset 20/20、routing-stall 20/20 通过；180 项 manifest 检查与逐轮同构建审核通过。详情见 [006d 报告](g7_candidate006d_acceptance_20261010.md)。同构建 PC receiver-exit 已完成 1 轮：主机恢复判据 1/1 通过，但板端 `status/fatal/transport` 各增加 2，`control` 不变；该批次未达到 clean-health，不能计作通过或用后续重载清零。candidate011 后续已上板并确认 receiver-exit 的 HELLO_ACK 超时。candidate012 新增 AP0 EP1 IN 所有权关联诊断；最新单轮结果和证据边界见 [candidate012 实板报告](g7_candidate012_tx_ownership_board_20261011.md)。旧 usbfix3 的通过批次不代替最终候选。

| 顺序 | 任务与交付 | 前置条件/完成判据 | 用户介入 |
|---|---|---|---|
| 0 | GitHub 上传 | 本轮 KX41 完成标记修复、严格采集器、实板 60 组验收摘要和 M02 20/20 探针脱敏记录随本次主分支提交同步；本机 ELF、原始 UART/JTAG 和 M02 日志留在忽略目录 | 无需动作 |
| 1 | candidate012 同构建 PC 退出/DTR 20 次 | candidate012 r3 离线预检 197 项、dry-run、基线认证视频通过。receiver-exit 单轮已证明中断前 4 帧认证有效；恢复 HELLO 后电脑 39 次读取为 0 字节，板端 HELLO/ACK 调用各 +1。新增 EP1 IN 所有权快照将完成计数从 169 增至 170；ACK 请求/期望长度均 51、残余 0、token=`0x8000`、match flags=`0x1f`。这证明该 dTD 与本次 ACK 调用关联并报告完成，但不证明电脑 CDC 应用收到数据；仍失败，不计通过，也未开始 20 轮。SDK 核查未支持 DTR 重建重置 toggle 的推断。下一步继续定位 USB 主机栈/总线交付或 CDC 接收边界；形成有证据的修正后再跑单轮 | 当前无需现场操作；新的单轮门禁通过后再安排重复批次 |
| 2 | candidate012 同构建物理 USB 拔插 20 次 | 第 1 项单轮和独立 20 轮门禁通过后逐轮提示；确认拔线时接收进程存活且认证流活动，PnP 断开/返回、新握手与认证帧，无恢复 JTAG 下载；独立记录 ready/epoch、cleanup 与原始 failure diagnosis，不以预期断连分类替代恢复判据 | 需要按提示拔插 USB Slave 数据线，保留 JTAG 和板卡供电 |
| 3 | G0 SD 独立启动、物理复位和 30 分钟冷启动 | 使用匹配 final2 BOOT.BIN/XSA/manifest 与专用 SD；按 G0 现场流程采集启动、一次物理复位、全断电上电后的 1800 秒日志 | 需要读卡器、可用于项目的专用 SD 卡及拨码/复位/上电操作。当前没有读卡器，板上原卡保持原样 |
| 4 | M02 摄像头物理启动补证 | 已完成：Explore 候选通过静态时序（WNS `+0.017 ns`/WHS `+0.041 ns`/DRC 0）、仿真 4/4、同会话 reset/config 20/20、20 次用户确认的整板断电/上电并逐轮 JTAG 配置 20/20、无模组 fail-closed。日志索引见 `build/m02_coldboot_cycles_20261011.jsonl`；JTAG 临时下载不代表 SD/Flash 独立启动，也未验证 DVP/JPEG 实际采集 | M02 现场门禁已完成；独立启动和采集按 G0/M03 单独安排 |
| 5 | Keccak KX41 全 60 组实板 KAT 与性能判定 | 已完成：新候选 `--verify-only` 715 项哈希复核通过；software、KX41 hardware、forced-timeout 三窗口各 60/60 KAT 通过。硬件 absorb 60 次、squeeze 182 blocks、正常硬件零回退，timeout 窗口 60/60 清 STATUS；硬件窗口耗时为 software 的 88.6%。只针对独立 KX41 候选，不代表视频工程性能；Keccak 内部 STATE/OUTPUT 未读回 | 无 |
| 6 | CPU 临时协议缓冲清理已实现，生产硬件/产品门禁待闭环 | candidate007 控制 helper harness、183 项预检与实板双会话/坏 Finished 回归通过；完整清零仍未证明。确定可信熵、密钥 provisioning/存储和 PS/cache/DDR/PL/USB 的清零边界，实现并取得读回/失败场景证据；JTAG 开发注入不等于生产安全 | 需要安全目标/部署条件信息时再集中询问 |
| 7 | 脱敏源码/证据审阅包已准备，正式比赛定稿待规则 | 按最终构建整理吞吐、窗口、延迟、错误计数、资源和原始证据索引；现有 15 秒 722 帧录像不外推长录可靠性。规则明确后制作指定论文/PPT/视频/附件 | 提供正式比赛规则、格式和截止时间 |

本轮实际产物见 [KX41 实板报告](keccak_sponge_x4_capture_fix_20261011.md)、[M02 实板探针](m02_sensor_reset_board_20261011.md)、[生产安全计划](production_security_plan_20261010.md)、[提交包计划](submission_delivery_plan_20261010.md)、[candidate011 离线报告](g7_candidate011_receiver_exit_offline_20261010.md)、[candidate011 实板报告](g7_candidate011_receiver_exit_board_20261011.md) 和 [candidate012 ownership 诊断报告](g7_candidate012_tx_ownership_board_20261011.md)。candidate012 新增的关联诊断排除了“旧发送完成被误认为本次 ACK 完成”的解释，但电脑仍报告 RX 零字节，实际 CDC 应用层交付和根因未确认。下一步定位主机 USB/CDC 边界，再决定是否需要新修正和单轮。G7 整体未通过。

第 1 项仍是恢复验收的下一项板测任务；当前没有需要用户现场操作的步骤，可继续电脑端证据归档、生产安全方案和比赛材料缺口整理。本轮 Keccak 测试仅临时 JTAG，不写 SD/Flash、不改变板上原卡。任何新候选单轮或长测前都需重新核验设备与固件身份，避免并发 reader/JTAG。

约 50 分钟长测沿用用户既有时长例外，始终标明未实测满 2 小时。camera-reset 与 routing-stall 证明受控 PL 故障下 S2MM Busy 到约 3 秒软件 deadline 的恢复，不宣称硬件 DMA timeout IRQ 或物理传感器拔除。下一次上板前仍须重新核验设备状态，不能将本次短时回归外推至持续在线或剩余 G7 场景。

续推进证据见 [身份核验优化板测](keccak_identity_cached_20261010.md)、[CPU 清理实施记录](security_cleanup_20261010.md) 和已更新的 [技术报告稿](technical_report.md)。新候选不覆盖旧006d验收；此前恢复冻结006d并复测140帧的记录仍有效，最新 3 秒认证视频回归也已通过。candidate011 的清理结果门槛和 HELLO/ACK 诊断已离线实现；candidate012 实板仍未通过 receiver-exit 单轮，因此 20 轮和物理 USB 拔插 20 轮尚未开始。当前无需用户现场操作；完成有证据的修正并通过新单轮后，再安排重复批次。

## 本轮续推进（2026-10-10）

截至 2026-10-10，用户所说的“摄像头恢复 20/20”对应 G7 的受控 camera-reset/PWDN 与 routing-stall，不能覆盖 M02 的物理冷启动和未插/错误接线退出。M02 物理门禁已在 2026-10-11 单独完成，见本计划顶部和 [M02 实板报告](m02_sensor_reset_board_20261011.md)。

Keccak KX41 已准备全 60 组 ML-KEM-512 KAT 的独立 ARM 固件，并推送于 GitHub `main` commit `9104394896499998f4c004e6a5fc8c27ce9f1a80`。离线构建、715 项哈希复核和 11 项严格 UART parser 测试通过；ELF SHA-256 为 `78b37fc5b8410cc8e868a8a2febc833e0397d0573c5d5c043399f53556a2824d`。本候选尚未上板，不能将此前 tcId 76 的有限板测扩展为 60 组实板通过。

虽然用户此前表示板卡已连接，本轮最新 Windows PnP 查询仍未枚举出 JTAG/USB 端点，因而不能启动本候选板测。下一步先恢复 JTAG 与 USB CDC 枚举，再以该严格固件运行三个窗口的完整 60 组采集；若任一硬件调用回退到软件、KAT 不匹配或 STATUS 未清零，parser 将拒绝该批次。
