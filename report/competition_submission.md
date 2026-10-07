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
| 当前电脑端交付 | `build/vitis/usbfix3_20261007` 有四套 ARM 固件、同 XSA 的 bitstream/PS 初始化、FSBL/BOOT.BIN 和 SHA-256 清单；启动来源/BSP/哈希预检通过，构建清单仍为 `board_validated=false`。目录被 Git 忽略，需重建或单独作为附件提供。 |
| 可复跑的离线检查 | `run_demo.ps1 -Mode Check` 覆盖 M04/M05 原生 XSim、M08 GCM、G6 内存 USB 集成及 USB 恢复 helper；最新结果见 [软件交付记录](software_ready.md)。不访问板卡。 |
| 本轮板卡证据 | 2026-10-07 的 G3 单帧及 G6 双会话已复现；最新 `usbfix3_20261007` 的 DTR 重连及接收进程强制退出后恢复通过自动板测，约 47 fps。具体构建和结果见 [G7 软件恢复记录](g7_software_recovery.md)，不能扩展为物理拔插或完整 G0/G7 通过。 |

## 提交前必须补齐

1. 用户照片已确认 `ZYNQ 7020` 标签、`CF7010B/7020B` 核心板、两颗海力士 DDR 和 `ATK-MC5640 V1.2` 摄像头；本轮 JTAG 已枚举 `xc7z020`。更换硬件或重新交付时仍须核对板型、器件及 DDR/引脚配置。
2. 本轮 G3 实拍结果已保存并复核 GCM 认证、JPEG 解码和邮箱清零。提交包仍需整理对应实拍、日志和构建身份，禁止将它算作 20 次冷启动或持续视频验收。
3. 若比赛要求 SD 卡冷启动，使用已生成并预检的同 XSA 启动镜像，另行实测；当前仅完成电脑端构建和 Bootgen 回读。
4. G6 认证视频/换钥及最新固件的自动连接恢复已有实机记录；补齐统一 Benchmark、丢帧/认证失败计数及演示材料，不能以短测替代故障次数要求。
5. 完成 G0、M13 与 G7 故障/恢复子项；约 50 分钟长测的时长豁免记录不替代拔线、摄像头异常和 DMA 超时测试。
6. 确认提交规则后决定是否需要单独论文/设计说明、答辩 PPT、演示视频、封面/声明、构建产物附件和指定命名格式。

## 重建与板测

本机 Vivado/Vitis 根目录为 `E:/fpg/2026.1`。先设置 `EYEPQC_TOOL_ROOT`，再依照 [M15/步骤](../doc/steps.md#19-m15调试观测与交付材料)、[G3 指南](../doc/g3.md) 和 [电脑构建记录](pc_build.md) 执行构建。上板首测只通过 JTAG 临时加载，不写 SD/QSPI/Flash。不要把忽略的 `build/` 中间产物误当成已经纳入 Git 的提交文件。
