# 下一阶段执行计划

更新：2026-10-11。M02 Explore 候选静态时序门禁、RTL 仿真 4/4、同会话传感器复位/配置 20/20、20 次用户确认的整板断电/上电后 JTAG 配置 20/20，以及无模组 fail-closed 均通过；探针不代表 SD/Flash 独立启动或 DVP/JPEG 采集。KX41 新候选 software/hardware/timeout fallback 三窗口全 60 组实板 KAT 通过，硬件窗口耗时为软件的 88.6%。candidate012 r3 的 receiver-exit 批次累计 13/20 个唯一轮次通过后，在 trial14 再次出现 HELLO_ACK 10 秒超时（COM16 已打开，39 次读取、0 字节）；此前 trial7 try01 也超时，try04 重试通过。ETW 无丢事件，但不含 USB 载荷/字节长度，根因仍未确认。candidate014 已完成同 HELLO 重试与缓存 ACK 重放修正，并在残留半帧时抑制重试；ARM GCC 构建、197 项哈希预检、dry-run、25 项 G6 测试和 9 项 batch runner 测试通过；`board_validated=false`，尚未下载到板卡，candidate012 旧轮次不能折算。candidate014 仍需新板上基线、ETW/AP0 单轮、20 轮 receiver-exit，之后另行完成物理 USB 拔插 20 轮。G0/G7 门禁彼此独立。官方 AMD 2026 赛道细则和格式尚未从公开官方渠道确认；已确认的其他赛道上传限制不套用。证据见 [M02 实板报告](m02_sensor_reset_board_20261011.md)、[candidate012 实板报告](g7_candidate012_tx_ownership_board_20261011.md)、[candidate014 离线候选报告](g7_candidate014_safe_hello_ack_retry_offline_20261011.md) 和[规则核验记录](contest_rules_review_20261011.md)。

## 本轮续推进（2026-10-11）

M02 默认实现曾以 WNS `-0.052 ns` 失败。相同 RTL/XDC 使用 `Explore` 与 `AggressiveExplore` 后均通过最终静态时序门禁，WNS `+0.017 ns`、WHS `+0.041 ns`、DRC 0 项；余量较小，AggressiveExplore 未进一步改善。固定 Explore bit/XSA/PS7 init hash 和复现实验见 [M02 构建报告](m02_timing_explore_20261011.md)。`sim/tb/test_m02.py` 重新运行 4/4 通过；探针支持 `-SensorResets 1` 和严格的 `-ExpectCameraFailure` 负向门禁。

KX41 采集器的完成标记已修正为固件实际输出 `KX41_BENCH_DONE`；13 项 parser/runner 测试通过。候选 `build/kx41_capturefix2_20261011` 的 `--verify-only` 复核 715 项哈希通过，ELF/XSA hash 和 WNS `+0.029 ns`/WHS `+0.082 ns` 匹配。新的 10.157 秒实板采集三窗口各有 60 个唯一 KAT 通过，硬件窗口回退为零；日志 SHA-256 为 `458059e8bb7e01a3953e9cb8e9c3dda983e0a4f8b066eae72ff23bc703bbc525`。旧错标记试跑保留为 runner 缺陷记录，不合并进验收。M02 同板完成 20 次传感器 reset/config probe（20/20，sensor ID `0x5640`、error=0），但未进行整板断电循环。详见 [KX41 实板报告](keccak_sponge_x4_capture_fix_20261011.md)、[机器记录](keccak_sponge_x4_capture_fix_20261011.json) 和 [M02 实板探针报告](m02_sensor_reset_board_20261011.md)。

USB EP0 所有权修复已完成。最终 candidate006d/v4 的短时认证视频、camera-reset 20/20、routing-stall 20/20 通过；180 项 manifest 检查与逐轮同构建审核通过。详情见 [006d 报告](g7_candidate006d_acceptance_20261010.md)。同构建 PC receiver-exit 已完成 1 轮：主机恢复判据 1/1 通过，但板端 `status/fatal/transport` 各增加 2，`control` 不变；该批次未达到 clean-health，不能计作通过或用后续重载清零。candidate011 后续已上板并确认 receiver-exit 的 HELLO_ACK 超时。candidate012 新增 AP0 EP1 IN 所有权关联诊断；最新单轮结果和证据边界见 [candidate012 实板报告](g7_candidate012_tx_ownership_board_20261011.md)。旧 usbfix3 的通过批次不代替最终候选。

| 顺序 | 任务与交付 | 前置条件/完成判据 | 用户介入 |
|---|---|---|---|
| 0 | GitHub 上传 | KX41、M02、candidate012 脱敏报告及验收材料已推送到主分支；本机 ELF、原始 UART/JTAG 和原始 M02 日志留在忽略目录 | 无需动作 |
| 1 | candidate014 HELLO_ACK 重试单轮与 receiver-exit 20 轮 | candidate014 ARM GCC 构建、197 项哈希预检、dry-run、25 项 G6 测试和 9 项 batch runner 测试通过，`board_validated=false`。先做新板上短基线，再通过 ETW/AP0 采集跑单轮；单轮通过后使用同一 ELF/manifest 完成 20/20 receiver-exit。candidate012 的 13 个通过轮不折算。 | 当前无需现场操作；板卡旁时确认 COM16/JTAG 后运行 `prj/run_g7_single_etw.ps1` |
| 2 | candidate014 同构建物理 USB 拔插 20 次 | 第 1 项单轮和 receiver-exit 20/20 均通过后逐轮提示；确认拔线时接收进程存活且认证流活动，PnP 断开/返回、新握手与认证帧，无恢复 JTAG 下载；独立记录 ready/epoch、cleanup 与失败诊断，不以预期断连分类替代恢复判据 | 需要按提示拔插 USB Slave 数据线，保留 JTAG 和板卡供电 |
| 3 | G0 SD 独立启动、物理复位和 30 分钟冷启动 | 使用匹配 final2 BOOT.BIN/XSA/manifest 与专用 SD；按 G0 现场流程采集启动、一次物理复位、全断电上电后的 1800 秒日志 | 需要读卡器、可用于项目的专用 SD 卡及拨码/复位/上电操作。当前没有读卡器，板上原卡保持原样 |
| 4 | M02 摄像头物理启动补证 | 已完成：Explore 候选通过静态时序（WNS `+0.017 ns`/WHS `+0.041 ns`/DRC 0）、仿真 4/4、同会话 reset/config 20/20、20 次用户确认的整板断电/上电并逐轮 JTAG 配置 20/20、无模组 fail-closed。日志索引见 `build/m02_coldboot_cycles_20261011.jsonl`；JTAG 临时下载不代表 SD/Flash 独立启动，也未验证 DVP/JPEG 实际采集 | M02 现场门禁已完成；独立启动和采集按 G0/M03 单独安排 |
| 5 | Keccak KX41 全 60 组实板 KAT 与性能判定 | 已完成：新候选 `--verify-only` 715 项哈希复核通过；software、KX41 hardware、forced-timeout 三窗口各 60/60 KAT 通过。硬件 absorb 60 次、squeeze 182 blocks、正常硬件零回退，timeout 窗口 60/60 清 STATUS；硬件窗口耗时为 software 的 88.6%。只针对独立 KX41 候选，不代表视频工程性能；Keccak 内部 STATE/OUTPUT 未读回 | 无 |
| 6 | G6 生产 profile 电脑端隔离已推进，生产安全仍未通过 | 生产构建已排除应用侧 ML-KEM 解封装、私钥导出及开发 mailbox/seed 符号；builder 要求 DRBG/provider/secure-cleanup 符号完整，并有 opaque-key 身份检查、provider 失败清理、输出区调用前清零等离线测试。g6s12 ARM ELF 使用故意 fail-closed 的临时 provider，128/128 全量电脑端回归通过，manifest 标记 `external_provider_unvalidated`、`board_validated=false`。这只证明软件隔离和构建门禁；仍须选定并审查真实熵源/provider、密钥 provisioning/持久化/轮换/RMA、secure boot/JTAG 生命周期，并完成 PS/cache/DDR/PL/DMA/USB 清零读回与现场验证。 | 当前可继续做源码审查和离线测试；真实 provider、部署威胁模型及所有板端读回须有平台方案和板卡后再闭环 |
| 7 | 脱敏源码/证据审阅包与公开规则核验已准备，正式比赛定稿待赛道细则 | 截止时间已由协办方页面列为 2026-11-04 18:00；AMD 具体组别、格式/评分和队长后台报名资格仍待确认。其他赛道公开上传限制不移用。现有 15 秒 722 帧录像不外推长录可靠性；Skill 与协作记录初版已补，项目级许可证/公开授权未决定 | 队长需在后台确认报名/资格并取得 AMD 赛道最新官方文件 |

本轮实际产物见 [KX41 实板报告](keccak_sponge_x4_capture_fix_20261011.md)、[M02 实板探针](m02_sensor_reset_board_20261011.md)、[生产安全计划](production_security_plan_20261010.md)、[提交包计划](submission_delivery_plan_20261010.md)、[官方规则核验](contest_rules_review_20261011.md)、[协作记录](collaboration_log.md)、[Skill README](../skill/eyepqc-fpga/README.md)、[许可证盘点](reuse_license_audit_20261011.md)、[candidate012 实板诊断报告](g7_candidate012_tx_ownership_board_20261011.md) 和 [candidate014 离线候选报告](g7_candidate014_safe_hello_ack_retry_offline_20261011.md)。candidate012 的 dTD 完成记录不能证明 CDC 应用层交付；candidate014 增加有界重试作为待实板验证的容错方案。G7 整体未通过。

第 1 项仍是恢复验收的下一项板测任务；目前已完成可离线推进的修正、构建、预检、测试与记录，本轮未访问板卡。candidate014 上板前仍须核验设备与固件身份；candidate012 的旧轮次不得移记到 candidate014。

约 50 分钟长测沿用用户既有时长例外，始终标明未实测满 2 小时。camera-reset 与 routing-stall 证明受控 PL 故障下 S2MM Busy 到约 3 秒软件 deadline 的恢复，不宣称硬件 DMA timeout IRQ 或物理传感器拔除。下一次上板前仍须重新核验设备状态，不能将本次短时回归外推至持续在线或剩余 G7 场景。

续推进证据见 [身份核验优化板测](keccak_identity_cached_20261010.md)、[CPU 清理实施记录](security_cleanup_20261010.md) 和已更新的 [技术报告稿](technical_report.md)。新候选不覆盖旧006d验收；此前恢复冻结006d并复测140帧的记录仍有效，最新 3 秒认证视频回归也已通过。candidate012 receiver-exit 批次累计 13 个唯一轮次通过，但两个 HELLO_ACK 超时使该批次失败；candidate014 增加缓存 ACK 重放和有限主机重试，需从新板上基线、单轮开始，再做 20/20 receiver-exit 和后续物理 USB 拔插 20/20。相应报告文件为 `g7_candidate014_safe_hello_ack_retry_offline_20261011.md`。

## 本轮续推进（2026-10-10）

截至 2026-10-10，用户所说的“摄像头恢复 20/20”对应 G7 的受控 camera-reset/PWDN 与 routing-stall，不能覆盖 M02 的物理冷启动和未插/错误接线退出。M02 物理门禁已在 2026-10-11 单独完成，见本计划顶部和 [M02 实板报告](m02_sensor_reset_board_20261011.md)。

Keccak KX41 已准备全 60 组 ML-KEM-512 KAT 的独立 ARM 固件，并推送于 GitHub `main` commit `9104394896499998f4c004e6a5fc8c27ce9f1a80`。离线构建、715 项哈希复核和 11 项严格 UART parser 测试通过；ELF SHA-256 为 `78b37fc5b8410cc8e868a8a2febc833e0397d0573c5d5c043399f53556a2824d`。本候选尚未上板，不能将此前 tcId 76 的有限板测扩展为 60 组实板通过。

虽然用户此前表示板卡已连接，本轮最新 Windows PnP 查询仍未枚举出 JTAG/USB 端点，因而不能启动本候选板测。下一步先恢复 JTAG 与 USB CDC 枚举，再以该严格固件运行三个窗口的完整 60 组采集；若任一硬件调用回退到软件、KAT 不匹配或 STATUS 未清零，parser 将拒绝该批次。
