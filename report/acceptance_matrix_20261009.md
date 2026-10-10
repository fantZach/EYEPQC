# EYEPQC 统一验收矩阵（建立 2026-10-09，更新 2026-10-10）

状态口径：**完成**仅指所列构建与证据满足该行判据；**部分**表示已有单轮/短窗口证据但重复或场景范围未满足；**未测**表示没有该门禁的有效测量；**失败**表示该批次发生失败，不将失败轮次删除或并入通过数。旧证据不自动代表当前候选构建。

| 门禁/判据 | 准确构建与现有证据 | 状态 | 下一步 | 需用户物理动作 |
|---|---|---|---|---|
| G0 工程重建：同一 M01 源、实现约束、XSA、匹配 BSP/FSBL 与启动镜像可追溯 | `g0_20261008b_startup_final2`；manifest build `9654837c3428`，BOOT.BIN SHA-256 `4c2760e609024f329f3f9d0c4aeb6d84c9de70872ce900e89d9d562a33410386`。当前 manifest/hash 预检通过；无本轮完整 Vivado/Vitis 重建 | 完成（产物预检）；本轮重建未复跑 | 需要新构建时使用新唯一 `BuildName`，重新生成实现证据和 manifest；不得复用本轮检查结果冒充重建 | 否（新构建为电脑端工作） |
| G0 临时 JTAG 启动、局部 DDR scratch、timer 与 H15 LED | 同一 final2；`data/captures/g0/20261008_jtag_led_probe_205256.jsonl` 和 `.result.json`。当前离线重验：BOOT_MODE `0x00`、30 秒、3 STAT、64 KiB scratch `full_ddr=no`、H15 人工观察通过 | 完成（仅 JTAG 探测范围） | 保留证据；不外推 SD、物理复位、冷启动或全片 DDR | 已有证据，无需本轮动作 |
| G0 SD 独立启动 | final2 的 BOOT.BIN 与 SD0-enabled XSA 已构建；当前没有本镜像 SD 启动记录 | 未测 | 需要可写入的专用 SD 介质后，按本报告现场步骤采集单次 SD 启动日志；现有卡不写 | 是：介质准备、对应跳帽/拨码、冷上电、LED 观察；用户本轮确认没有读卡器，板上有一张 SD 卡并保持原样 |
| G0 物理复位后恢复 | 没有本轮 final2 的 SD 物理复位证据；JTAG reset/load 不替代用户按板载复位键 | 未测 | 单独跑 `reset_probe`，验证恰好两次 SD BOOT 且第二次 READY/STAT | 是：确认板卡复位键并恰好按一次 |
| G0 断电冷启动稳定性 | final2 当前仅有 30 秒 JTAG；无 SD 全断电后 30 分钟连续日志 | 未测 | SD 启动后连续 1800 秒；保存 JSONL 和 result；不加 20 次 G0 启动要求 | 是：全断电再上电、保持板卡和 UART 采集 30 分钟 |
| M02 摄像头冷启动与错误接线退出（独立于 G0） | 现有材料不足以证明 20 次冷启动和未插/错误接线退出要求已完整通过；G0 的单次/30 分钟判据不覆盖 M02 | 未测/待补证 | 按 M02 独立批次和原判据收集结果，不并入 G0 的单次启动证据 | 是：摄像头接线/启动场景；不在本轮进行 |
| G1 摄像头 JPEG 至 DDR、解码和统计 | 历史 M05/G3 实拍含 JPEG 解码、连续帧统计；`report/competition_submission.md` 与 `doc/steps.md` 记录 1000 帧结果。与当前 G0 门禁分开 | 完成（已有历史证据；提交包需整理关联素材） | 交付时附上准确构建、帧长、FPS 和对应原始素材索引 | 否（复核/整理） |
| G2 DMA→PL AES-GCM→DDR 黄金参考比对及长度/背压 | `doc/steps.md` 记载 21 个固定包、尾长覆盖、Tag 验证；M08 另有仿真背压 | 完成（已有证据） | 汇总统一 Benchmark 时链接现有证据，不重复宣称整机 USB 通过 | 否 |
| G3 摄像头→DDR→AES-GCM→主机认证解密 | 历史 G3 有实拍逐包认证/解密、JPEG 可解码及 1000 帧快速子采样数据；不同模式分别标明 | 完成（限定离线视频链路） | 交付明确指出连续任务的末帧认证范围，不把 G3 等同 USB G4/G5 | 否 |
| G4 明文 USB 摄像头流与显示 | `doc/steps.md` / `doc/goals.md` 记载历史 30 分钟约 47.258 fps | 完成（历史构建/证据范围） | 在统一 Benchmark 关联构建及原始记录 | 否 |
| G5 PL AES-GCM USB 视频、Tag 拒绝 | 历史 60 秒约 47.270 fps，真实包 Tag 篡改被拒绝 | 完成（测试密钥限定） | 明示固定测试密钥不代表生产密钥方案 | 否 |
| G6 ML-KEM 会话、Finished、重放保护和换钥 | 开发态 JTAG 注入私钥/seed；历史实板双会话、认证流和篡改拒绝记录 | 完成（开发态功能）；生产安全未通过 | 生产密钥/熵源路线单独闭环 | 否（设计/实现工作） |
| G7 主机接收进程退出恢复 | 旧 usbfix3_20261007 下 20/20；最终 006d 尚无同构建完整批次 | 历史构建完成；006d 待测 | 先重验 CDC/manifest/无重复 reader，再跑同一 006d 的 PC 退出/DTR 20 次；新 HELLO、认证帧和无 JTAG 重载逐轮留证 | 否（自动故障脚本；接线异常时介入） |
| G7 USB 物理拔插恢复 | 旧 usbfix3 严格 active-stream 20/20（原17+补3）；最终 006d 尚无同构建完整批次 | 历史构建完成；006d 待测 | PC 退出回归后，同一 006d 做物理 USB 拔插 20 次；旧记录不代替 | 是：按提示拔插 USB Slave 数据线，保持供电/JTAG |
| G7 候选 USB 枚举与 EP0 所有权 | candidate006d/v4 共享 SETUP gate、静态 buffer 所有权、QH cache line/完成状态和 CDC 类错误路径已修复；USB mock 3/3、ARM 链接、180 项 manifest 检查和实板认证短测通过。candidate004 失败保留，candidate005 未上板 | 修复及所列验证完成；不能推出所有 USB 故障已通过 | 同构建 PC 退出/DTR 与物理 USB 回归；详见 [006d 报告](g7_candidate006d_acceptance_20261010.md) | 当前整理不需动作 |
| G7 摄像头/DMA 异常恢复候选 | 最终 006d 同 manifest/ELF/XSA：camera-reset 20/20、routing-stall 20/20；S2MM 实际 Busy 至 3000001–3000002 us 软件 deadline，新 HELLO/session/key 和认证视频恢复；故障计数各 +1，fatal/control/transport 无增加；无恢复 JTAG 重载 | 完成（受控 PL 故障和软件 deadline 范围） | 保留 [逐轮摘要](g7_candidate006d_acceptance_20261010.json)；不外推物理传感器拔除或硬件 timeout IRQ。G7 整体还缺同构建 USB/PC 回归 | 否（两组已封存）；物理摄像头场景另行安排 |
| G7 长时间运行 | 约 50 分钟长测按用户例外记录，未实测满 2 小时 | 完成（时长例外）；2 小时实测未测 | 保留豁免与实测时长的区别，不写成 2 小时实测通过 | 否（若用户要求补实测则需占板长测） |
| 实机录像/导出/回放 | `report/demo_software_ready.md`：15 秒窗口、722/722 回调帧保存，MP4/AVI 各解码 722 帧；包含换钥空档 | 完成（短测） | 长录与不同负载仍需独立证据；不把 722 帧短测写成长时可靠性 | 否；A 独占板卡，若连接/供电异常才用户介入 |
| 生产密钥、可信熵、全域清零 | 已完成源码审阅与 [实施计划](production_security_plan_20261010.md)，既有显式清理范围逐项列明；JTAG/主机 seed 仍是开发态，未验证可信熵、生产存储和全域清零 | 源审阅/计划完成；生产安全未通过 | 按实际熵/存储可行性和产品威胁模型建立接口、fail-closed 与秘密清理矩阵；安全目标需要时集中确认 | 需要部署/器件方案信息时再询问；本轮未写永久配置 |
| C Keccak PS AXI-Lite 隔离工程 | 原 route4k 实现/XSA 哈希不变；新 safe_elfs 修复 MMIO 条件与 printf ABI 后，实板 SW 1/HW 3 轮，ID/version、tc76 KAT、96 HW 调用及 96 timeout fallback 通过。完整 ML-KEM HW 约慢 8.6%，STATUS 清理为 0 | 功能在所列范围完成；本版无加速收益；全域清零读回未证 | 按用户本轮授权提前测试，结束已恢复006d。优化 MMIO/批处理后再实测，不把当前隔离 XSA 代替视频工程；见 [Benchmark](keccak_board_benchmark_20261010.md) | 无需当前物理动作 |
| 统一 Benchmark 和比赛材料 | 新增 `report/benchmark_summary_20261009.json`，显式列出 10 条隔离记录；包括 C route4k 离线 Keccak 实现/XSA 哈希验证（不含板测/性能指标）；脚本/测试/字段说明见 `prj/collect_benchmark_summary.py`、`sim/tb/test_benchmark_summary.py`、`report/benchmark_summary_20261009.md` | 电脑端汇总完成；正式规则/格式与答辩材料待定 | 缺少结构化原始数据的 G4/G5 和重复批次仍保持未汇总；继续收集同构建下的窗口、分辨率、吞吐、延迟与资源数据；新增 006d 固定来源逐轮独立摘要；规则未给定前不造论文/PPT/评分数据 | 否 |

## 本轮可直接完成的用户侧操作

完成 G0 的 SD/复位/冷启动门禁前，现场需提供读卡器和可写入的专用 SD 卡，并确认对应板卡版本的 SD 启动拨码/跳帽和复位键；板上现有 SD 卡保持原样，不写入。之后由执行代理或根代理作为唯一板卡拥有者安排独占窗口，按 [B 线流程](parallel_B_20261009.md) 执行并留存日志。

## 2026-10-10 续推进补充

Keccak 身份核验优化版三次独立启动，每个三次解封装窗口逐次 tcId76 KAT/96 dispatch、timeout fallback通过；HW仍约慢8.4%，未集成视频。candidate007 的CPU控制缓冲清理已有C harness/183项构建预检/目标反汇编和双会话284帧、坏Finished拒绝功能回归；这些均不证明全域清零/生产安全。旧006d的恢复批次保持原身份，结束后恢复旧固件并复测140帧。详情见 [新Keccak报告](keccak_identity_cached_20261010.md) 和 [清理报告](security_cleanup_20261010.md)。
