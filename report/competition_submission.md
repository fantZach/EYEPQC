# 比赛提交检查表

更新：2026-10-06。本文件是当前源码仓库的提交索引，不代表比赛组委会验收；正式格式与评分规则尚未提供。

**同日更新：** 新的 `build/vitis/software_ready` 已具备 G3/G4/G5/G6、FSBL 和 `BOOT.BIN`；
M04/M05 原生 XSim 已通过，软件修正与统一入口见 [软件阶段交付](software_ready.md)。
电脑端缺口已补齐；SD 启动和所有实板门禁仍须单独验证。
首次实机使用 [bringup 指南](../doc/bringup.md)，不要继续使用源码哈希已失效的旧 `g3_delivery`。

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
| 当前电脑端交付 | `build/vitis/software_ready` 有四套 ARM 固件、同 XSA 的 bitstream/PS 初始化、FSBL/BOOT.BIN 和 SHA-256 清单；预检通过，`board_validated=false`。目录被 Git 忽略，需重建或单独作为附件提供。 |
| 当前可复跑的离线检查 | 17 个入口全部通过，含 M04/M05 原生 XSim、M08 GCM 和 G6 内存 USB 集成。详细日志在 `build/software_checks/final_goal`，软件证据范围见 [软件交付记录](software_ready.md)。 |
| 历史板卡门禁 | G2/G3/G4/G5/G6 及 M01/M05/M09 等历史板测记录见各模块报告；它们是此前 CF7020B 的证据，不自动证明当前这份 G3 产物已在用户手上的板卡运行。 |

## 提交前必须补齐

1. 用户照片已确认 `ZYNQ 7020` 标签、`CF7010B/7020B` 核心板、两颗海力士 DDR 和 `ATK-MC5640 V1.2` 摄像头；首次下载前仍需通过 JTAG 核对器件 IDCODE 与 `xc7z020clg400-2` 相符。
2. 连接 JTAG 和 OV5640，在当前 G3 清单上完成一次新鲜上板测试，保存 `G3_BOARD_OK`、`result.json`、实拍 JPEG 和工具日志，并复核无丢帧/溢出。
3. 若比赛要求 SD 卡冷启动，使用已生成并预检的同 XSA 启动镜像，另行实测；当前仅完成电脑端构建和 Bootgen 回读。
4. G3 实机通过后，以当前 G6 ELF 完成 USB 握手、认证视频与换钥复验；内存 USB 和历史板测不能替代该门禁。
5. 完成 G0、M13 与 G7 故障/恢复子项；约 50 分钟长测的时长豁免记录不替代拔线、摄像头异常和 DMA 超时测试。
6. 确认提交规则后决定是否需要单独论文/设计说明、答辩 PPT、演示视频、封面/声明、构建产物附件和指定命名格式。

## 重建与板测

本机 Vivado/Vitis 根目录为 `E:/fpg/2026.1`。先设置 `EYEPQC_TOOL_ROOT`，再依照 [M15/步骤](../doc/steps.md#19-m15调试观测与交付材料)、[G3 指南](../doc/g3.md) 和 [电脑构建记录](pc_build.md) 执行构建。上板首测只通过 JTAG 临时加载，不写 SD/QSPI/Flash。不要把忽略的 `build/` 中间产物误当成已经纳入 Git 的提交文件。
