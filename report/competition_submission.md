# 比赛提交检查表

更新：2026-10-11。本文件是当前源码仓库的提交索引，不代表比赛组委会验收；正式格式与评分规则尚未提供。
历史发布范围见 [2026-10-08 同步记录](github_sync_20261008.md)；本轮状态、脱敏证据摘要和隔离 Keccak 交付分别见 [验收矩阵](acceptance_matrix_20261009.md)、[Benchmark 汇总](benchmark_summary_20261009.md) 与 [C 线报告](parallel_C_20261009.md)。

**同日更新：** 新的 `build/vitis/software_ready` 已具备 G3/G4/G5/G6、FSBL 和 `BOOT.BIN`；
M04/M05 原生 XSim 已通过，软件修正与统一入口见 [软件阶段交付](software_ready.md)。
该轮电脑端构建缺口已补齐；后续实板通过项与剩余门禁分别列于下文。
首次实机使用 [bringup 指南](../doc/bringup.md)，不要继续使用源码哈希已失效的旧 `g3_delivery`。

最新 USB 修复及同构建 40 轮恢复的审核见 [006d 报告](g7_candidate006d_acceptance_20261010.md) 与 [本轮同步](github_sync_20261010.md)。

2026-10-11 新增：KX41 独立候选全 60 组三窗口实板 KAT 和性能结果见 [KX41 实板报告](keccak_sponge_x4_capture_fix_20261011.md)；M02 Explore 候选传感器复位探针 20/20 见 [M02 实板报告](m02_sensor_reset_board_20261011.md)。M02 整板冷启动、无摄像头 fail-closed、G0/G7 未完成门禁仍按验收矩阵保留。

## 提交包索引

- 项目目标、系统边界与威胁模型：[项目说明](../doc/goals.md)、[README](../README.md)。
- 实施顺序和逐项判据：[步骤与验收](../doc/steps.md)。
- RTL、PS 与主机端实现：`src/rtl/`、`src/ps/`、`src/host/`。
- 自动化构建及上板脚本：`prj/`；仿真和主机检查：`sim/`。
- 协议向量与公开算法测试素材：`sim/vectors/`、`data/kat/`。
- 板卡/工具来源、模块报告、进度和本轮电脑构建证据：`board/README.md`、`report/`。
- 设计汇总与协作纠错记录：[技术报告草稿](technical_report.md)、[协作记录](collaboration_log.md)。
- 项目级复用工作流：[EYEPQC FPGA Skill](../skill/eyepqc-fpga/SKILL.md)。

## 已有证据

| 范围 | 证据与状态 |
|---|---|
| Vivado 2026.1 综合/实现/bitstream | 当前 XSA 器件为 `xc7z020clg400-2`；时序 WNS +0.013 ns、WHS +0.018 ns。DRC 保留 `PLCK-12` 时钟专用路由警告，不作零警告宣称。 |
| 当前电脑端交付 | `build/vitis/usbfix3_20261007` 有四套 ARM 固件、同 XSA 的 bitstream/PS 初始化、FSBL/BOOT.BIN 和 SHA-256 清单；启动来源/BSP/哈希预检通过，构建清单仍为 `board_validated=false`。目录被 Git 忽略，需重建或单独作为附件提供。 |
| 可复跑的离线检查 | `run_demo.ps1 -Mode Check` 覆盖 M04/M05 原生 XSim、M08 GCM、G6 内存 USB 集成及 USB 恢复 helper；最新结果见 [软件交付记录](software_ready.md)。不访问板卡。 |
| 2026-10-09 离线交付（历史范围） | B 的 G0 离线复核、统一验收矩阵、现场流程与脱敏 Benchmark 已完成；fixture 单测 12/12。C 的独立 Keccak route4k PS+PL 工程、匹配 XSA/bitstream 和两种 A9 固件已通过离线构建/hash 检查，但未上板、未测性能，不能作为加速收益证据。 |
| 本轮板卡证据 | candidate006d/v4 已完成 EP0 所有权修复；180 项哈希检查通过，短测 471 帧、47.3579 fps；camera-reset 与 routing-stall 各 20/20，逐轮同 manifest/ELF/XSA，新握手/认证帧及计数器通过，无恢复 JTAG 重载。受控 PL 故障和约 3 秒软件 deadline 与物理传感器拔除/硬件 timeout IRQ 区分。旧 usbfix3 的 PC 退出和严格物理 USB 拔插各 20 次保留历史身份；最终 006d 的这两项待复测。candidate004 枚举失败、candidate005 未上板不改写。G0/G7 整体尚未通过，见 [006d 报告](g7_candidate006d_acceptance_20261010.md) 与 [验收矩阵](acceptance_matrix_20261009.md)。 |
| 新增 Keccak 实板证据 | safe_elfs 配匹配 route4k XSA：SW 1/HW 3 轮、KAT/ID/真实硬件调用及 timeout fallback 通过；端到端解封装 HW 约慢 8.6%，没有加速收益。STATUS 清理与全域清零区别见 [实板报告](keccak_board_benchmark_20261010.md)。 |
| 电脑端材料归档 | 安全源码审阅与实施路线、脱敏源码/证据审阅包生成器及内容 hash/路径核对完成，见 [安全计划](production_security_plan_20261010.md)、[交付计划](submission_delivery_plan_20261010.md)。正式规则未提供，审阅包不作最终规则符合性声明。 |

## 提交前必须补齐

演示面板、换钥/篡改按钮和 JPEG 序列录制/回放已完成电脑端实现和测试，
见 [演示完成记录](demo_software_ready.md)；实机 UI、15 秒录像/回放/MP4/AVI 导出已短测通过，
722/722 帧保存并解码。长时间录像和最终比赛演示视频仍待完成。

1. 用户照片已确认 `ZYNQ 7020` 标签、`CF7010B/7020B` 核心板、两颗海力士 DDR 和 `ATK-MC5640 V1.2` 摄像头；本轮 JTAG 已枚举 `xc7z020`。更换硬件或重新交付时仍须核对板型、器件及 DDR/引脚配置。
2. 本轮 G3 实拍结果已保存并复核 GCM 认证、JPEG 解码和邮箱清零。提交包仍需整理对应实拍、日志和构建身份，禁止将它算作 20 次冷启动或持续视频验收。
3. 若比赛要求 SD 卡冷启动，使用已生成并预检的同 XSA 启动镜像，另行实测；G0 final2 已完成临时 JTAG、LED 与30秒局部DDR/定时器检查，SD独立启动及30分钟冷启动仍未验收。本轮已确认没有读卡器，板上 SD 卡保持原样、不写入。
4. G6 认证视频/换钥及最新固件的自动连接恢复已有实机记录；统一脱敏 Benchmark 已建立，但缺少结构化来源的历史项仍需逐项补证；丢帧/认证失败计数及演示材料不能以短测替代长测。
5. 完成 G0、M13 与剩余 G7 子项：006d 的受控摄像头 reset/PWDN 与 routing-stall 各 20/20 已通过，继续同构建 PC 退出/DTR 20 次及物理 USB 拔插 20 次。旧 usbfix3 批次不替代；约 50 分钟时长例外不写成实测 2 小时。物理摄像头场景和 M02 冷启动要求另行收集，见 [执行计划](next_stage_plan.md)。
6. 确认提交规则后决定是否需要单独论文/设计说明、答辩 PPT、演示视频、封面/声明、构建产物附件和指定命名格式。

## 重建与板测

本机 Vivado/Vitis 根目录为 `E:/fpg/2026.1`。先设置 `EYEPQC_TOOL_ROOT`，再依照 [M15/步骤](../doc/steps.md#19-m15调试观测与交付材料)、[G3 指南](../doc/g3.md) 和 [电脑构建记录](pc_build.md) 执行构建。上板首测只通过 JTAG 临时加载，不写 SD/QSPI/Flash。不要把忽略的 `build/` 中间产物误当成已经纳入 Git 的提交文件。
