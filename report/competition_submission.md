# 比赛提交检查表

更新：2026-10-11。本文件是当前源码仓库的提交索引，不代表比赛组委会验收。赛事协办方赛程页和高校通知列出作品提交截止为 2026-11-04 18:00；AMD 具体赛道规则、格式和队伍资格仍需在官网/报名后台核验，见[交付计划](submission_delivery_plan_20261010.md)。
历史发布范围见 [2026-10-08 同步记录](github_sync_20261008.md)；本轮状态、脱敏证据摘要和隔离 Keccak 交付分别见 [验收矩阵](acceptance_matrix_20261009.md)、[Benchmark 汇总](benchmark_summary_20261009.md) 与 [C 线报告](parallel_C_20261009.md)。

**同日更新：** 新的 `build/vitis/software_ready` 已具备 G3/G4/G5/G6、FSBL 和 `BOOT.BIN`；
M04/M05 原生 XSim 已通过，软件修正与统一入口见 [软件阶段交付](software_ready.md)。
该轮电脑端构建缺口已补齐；后续实板通过项与剩余门禁分别列于下文。
首次实机使用 [bringup 指南](../doc/bringup.md)，不要继续使用源码哈希已失效的旧 `g3_delivery`。

历史 candidate006d camera-reset/routing-stall 恢复批次见 [006d 报告](g7_candidate006d_acceptance_20261010.md)。candidate012 r3 的 receiver-exit 批次累计 13/20 后因两次 HELLO_ACK 超时失败；candidate014 已完成 ACK 缓存重放/有限重试及半帧保护的离线候选，测试与哈希预检通过，但 `board_validated=false`、尚未上板。详见 [candidate012 实板诊断](g7_candidate012_tx_ownership_board_20261011.md) 和 [candidate014 离线候选报告](g7_candidate014_safe_hello_ack_retry_offline_20261011.md)。G7 仍未通过。

2026-10-11 新增：KX41 独立候选全 60 组三窗口实板 KAT 和性能结果见 [KX41 实板报告](keccak_sponge_x4_capture_fix_20261011.md)；M02 Explore 候选的 20 次整板断电/上电后 JTAG 配置和无摄像头 fail-closed 均完成，证据见 [M02 实板报告](m02_sensor_reset_board_20261011.md)。M02 的 SD/Flash 独立启动和 DVP/JPEG 实拍、G0/G7 其他未完成门禁仍按验收矩阵保留。

## 提交包索引

- 项目目标、系统边界与威胁模型：[项目说明](../doc/goals.md)、[README](../README.md)。
- 实施顺序和逐项判据：[步骤与验收](../doc/steps.md)。
- RTL、PS 与主机端实现：`src/rtl/`、`src/ps/`、`src/host/`。
- 自动化构建及上板脚本：`prj/`；仿真和主机检查：`sim/`。
- 协议向量与公开算法测试素材：`sim/vectors/`、`data/kat/`。
- 板卡/工具来源、模块报告、进度和本轮电脑构建证据：`board/README.md`、`report/`。
- 设计汇总与协作纠错记录：[技术报告草稿](technical_report.md)、[协作记录](collaboration_log.md)。
- 项目级复用工作流：[EYEPQC FPGA Skill](../skill/eyepqc-fpga/SKILL.md)、[案例与验证边界](../skill/eyepqc-fpga/README.md)。
- 开源准备：[代码复用与许可证初步盘点](reuse_license_audit_20261011.md)；根项目许可证和公开授权未决定。

## 已有证据

| 范围 | 证据与状态 |
|---|---|
| G3 Vivado 2026.1 综合/实现/bitstream | G3 implementation report 的器件为 `xc7z020clg400-2`；时序 WNS +0.013 ns、WHS +0.018 ns。DRC 保留 `PLCK-12` 时钟专用路由警告，不作零警告宣称；该时序记录不替代 candidate012/KX41 各自的实现报告。 |
| 已归档电脑端交付基线 | `build/vitis/usbfix3_20261007` 有四套 ARM 固件、同 XSA 的 bitstream/PS 初始化、FSBL/BOOT.BIN 和 SHA-256 清单；启动来源/BSP/哈希预检通过，构建清单仍为 `board_validated=false`。目录被 Git 忽略，需重建或单独作为附件提供；该路径不等同 candidate012 板测构建。 |
| 可复跑的离线检查 | `run_demo.ps1 -Mode Check` 覆盖 M04/M05 原生 XSim、M08 GCM、G6 内存 USB 集成及 USB 恢复 helper；最新结果见 [软件交付记录](software_ready.md)。不访问板卡。 |
| 2026-10-09 离线交付（历史范围） | B 的 G0 离线复核、统一验收矩阵、现场流程与脱敏 Benchmark 已完成；fixture 单测 12/12。C 的独立 Keccak route4k PS+PL 工程、匹配 XSA/bitstream 和两种 A9 固件已通过离线构建/hash 检查，但未上板、未测性能，不能作为加速收益证据。 |
| G7 最新板卡证据 | 最新板测仍是 candidate012：receiver-exit 批次 13/20 后失败，trial 7/14 在 HELLO_ACK 等待处超时；同期普通 CDC 重连认证 141 帧/1,130 包、47.672 fps。candidate014 只有软件构建/离线证据，尚未下载到板卡。历史 candidate006d camera-reset/routing-stall 各 20/20 仅按原构建身份保留。G7 整体未通过，见 [candidate012 报告](g7_candidate012_tx_ownership_board_20261011.md)、[candidate014 报告](g7_candidate014_safe_hello_ack_retry_offline_20261011.md)、[006d 报告](g7_candidate006d_acceptance_20261010.md) 与 [验收矩阵](acceptance_matrix_20261009.md)。 |
| KX41 实板证据 | 独立候选 software、hardware 和 timeout fallback 三窗口各 60/60 KAT；硬件窗口 ticks 为软件的 88.6%。未集成视频固件，也没有读回 Keccak 内部 STATE/OUTPUT，见 [KX41 实板报告](keccak_sponge_x4_capture_fix_20261011.md)。 |
| M02 实板证据 | 用户确认的 20 次整板断电/上电后 JTAG 配置 20/20；无摄像头 fail-closed 通过。SD/Flash 启动和 DVP/JPEG 实拍未测，见 [M02 报告](m02_sensor_reset_board_20261011.md)。 |
| 历史 Keccak 实板证据 | safe_elfs 配匹配 route4k XSA 的 tcId76 路径中 HW 约慢 8.6%；STATUS 清理不证明全域清零，见 [旧实板报告](keccak_board_benchmark_20261010.md)。 |
| 电脑端材料归档 | 安全源码审阅与实施路线、脱敏源码/证据审阅包生成器及内容 hash/路径核对完成，见 [安全计划](production_security_plan_20261010.md)、[交付计划](submission_delivery_plan_20261010.md)。截止时间已查到，赛道细则与格式仍待官方核实；审阅包不作最终规则符合性声明。 |

## 提交前必须补齐

演示面板、换钥/篡改按钮和 JPEG 序列录制/回放已完成电脑端实现和测试，
见 [演示完成记录](demo_software_ready.md)；实机 UI、15 秒录像/回放/MP4/AVI 导出已短测通过，
722/722 帧保存并解码。长时间录像和最终比赛演示视频仍待完成。

1. 用户照片已确认 `ZYNQ 7020` 标签、`CF7010B/7020B` 核心板、两颗海力士 DDR 和 `ATK-MC5640 V1.2` 摄像头；本轮 JTAG 已枚举 `xc7z020`。更换硬件或重新交付时仍须核对板型、器件及 DDR/引脚配置。
2. 本轮 G3 实拍结果已保存并复核 GCM 认证、JPEG 解码和邮箱清零。提交包仍需整理对应实拍、日志和构建身份，禁止将它算作 20 次冷启动或持续视频验收。
3. 若比赛要求 SD 卡冷启动，使用已生成并预检的同 XSA 启动镜像，另行实测；G0 final2 已完成临时 JTAG、LED 与30秒局部DDR/定时器检查，SD独立启动、物理复位及30分钟冷启动仍未验收。用户目前没有读卡器，板上 SD 卡保持原样、不写入。
4. G6 认证视频/换钥及最新固件的自动连接恢复已有实机记录；统一脱敏 Benchmark 已建立，但缺少结构化来源的历史项仍需逐项补证；丢帧/认证失败计数及演示材料不能以短测替代长测。
5. G7 下一步先用 candidate014 做新板上短基线和 ETW/AP0 单轮；通过后，同一 ELF/manifest 从零跑 20 轮接收进程退出，再单独进行 20 轮物理 USB 拔插。candidate012 的 13 个通过轮及 candidate006d 的受控 camera-reset/PWDN、routing-stall 各 20/20 都只作为原构建的历史证据。约 50 分钟时长例外不写成实测 2 小时，见 [执行计划](next_stage_plan.md)。
6. M02 的 20 次上电配置、无摄像头 fail-closed 现场操作已完成；若提交范围需要，再单独安排 SD 启动、物理复位、长时冷启动或 DVP/JPEG 实拍，不把不同门禁合并。
7. 从官网/报名后台获取 AMD 具体赛道最新细则并确认队伍资格；据此定稿作品报告、演示视频、声明和附件格式。根项目许可证尚未确定，先完成[版权与依赖盘点](reuse_license_audit_20261011.md)并获得团队授权，再讨论公开范围。

## 重建与板测

本机 Vivado/Vitis 根目录为 `E:/fpg/2026.1`。先设置 `EYEPQC_TOOL_ROOT`，再依照 [M15/步骤](../doc/steps.md#19-m15调试观测与交付材料)、[G3 指南](../doc/g3.md) 和 [电脑构建记录](pc_build.md) 执行构建。上板首测只通过 JTAG 临时加载，不写 SD/QSPI/Flash。不要把忽略的 `build/` 中间产物误当成已经纳入 Git 的提交文件。
