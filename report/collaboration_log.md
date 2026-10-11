# 协作与自我纠错记录

更新：2026-10-11。此记录概括仓库可追溯的决策与修正，不把历史对话或验证结果扩大解释为硬件验收。新增记录按证据类型保留边界；原始日志仍按各板测报告中的路径管理。

2026-10-06 用户指定先完成软件、到实机验证时停止。当日已完成 17 项电脑回归、四套固件、
FSBL/启动镜像和软件预检；补齐经典/SDT BSP 适配并修正 G6 高精度计时。
新状态见 [软件阶段交付](software_ready.md)；以下早期 XSim/FSBL 缺口记录保留为过程证据，
当前以新状态为准。没有实机下载或写入启动介质。

## 协作决策

- 按用户“能提交比赛”的目标，先推进电脑端可复现构建、模块验证、报告和交付索引；物理板卡测试必须单独记录。
- Vivado 2026.1 已用于生成 Zynq-7020 目标的 bitstream/XSA。2026-10-06 用户实物照片显示 `ATK-DIY7010/7020P`、`CF7010B/7020B`、`ZYNQ 7020` 标签和 `ATK-MC5640 V1.2` 摄像头；当日 JTAG 未连接，照片不能替代 IDCODE 或新镜像板测。2026-10-11 的后续记录已确认 JTAG 与视频 CDC `03FD:7020` 枚举正常，并完成 candidate012 的新一轮只读诊断和普通 CDC 基线；这些新状态以对应日期的 G7 报告为准。
- 采用开发态测试密钥时，在报告中明确其不构成生产密钥注入、熵源或安全部署验收。
- 没有比赛评分细则或指定模板，因此技术报告保持为可改写草稿，不声称符合某个未知赛制格式。

## 已确认的纠错

| 发现 | 修正 | 复核范围 |
|---|---|---|
| UART/DMA 查询参数在经典与 SDT BSP 中含义不同 | UART 分别使用设备 ID/基地址，DMA 使用对应基地址查询 API | 实际经典 BSP 配置表在 PC 上验证；四套 ARM ELF 构建通过，尚待实机复验 |
| Windows CRLF 环境下确定性向量文件与测试比较不一致 | 统一生成/比较时的换行规范 | `generate_vectors.py --check` 验证 5 个向量文件 |
| G3/G6 工具根目录写死为旧安装路径 | 增加 `EYEPQC_TOOL_ROOT` 环境变量和 `--tool-root` 参数 | 脚本静态解析通过；默认值仍为兼容旧环境 |
| 供应商导入脚本使用作者机器上的固定路径 | 改为要求调用者显式传入来源目录 | PowerShell 参数/调用约定已核对；不会覆盖已有导入文件 |
| 硬件版本一度仅根据板系名称推断 | 更新为引用实物照片可读标签，并保留 JTAG IDCODE 确认项 | XSA `xc7z020clg400-2` 与照片上的 7020 标签相符；实际器件仍未通过 JTAG 核验 |

## 验证与边界（截至 2026-10-06）

- 本轮记录在 [电脑端构建与离线验证](pc_build.md)；通过的当前电脑端检查包括 M00～M03、M07～M10、M12、G3 主机协议和 G5。M05 帧所有权、路由及缓冲区三项中两项通过，原生集成 XSim 失败。
- M04/M05 原生 XSim 本轮因本机 Vivado 随附 MinGW GCC 6.2 编译快照失败而未通过；MSYS2 Icarus 13 偶发在写出非空 VVP 产物后以访问冲突退出。共享测试助手只接受该特定退出码和非空产物，并仍要求 `vvp` 实际运行通过完整功能标记。历史通过记录单独保留，不能代替本轮复现。
- 当前 G3 ELF/bitstream/XSA 清单的 `board_validated` 为 `false`。连接 JTAG 并核实 IDCODE 后，仍需将当前清单下载到板卡、接入摄像头并保存新鲜结果。
- 尚未创建当前 G3 的 `BOOT.BIN`。已尝试由当前 XSA 创建 Vitis 2026.1 平台并生成匹配 FSBL，但平台生成返回 `Error in generating Processor List`。因此没有用其他 XSA 的 FSBL 拼装镜像；现有 JTAG 首测流程也不写 SD/QSPI/Flash。若赛制要求 SD 卡冷启动，须修复 Processor List/Lopper 生成环境，再生成并实测启动镜像。

## 2026-10-11 续推进：实板证据和材料纠错

| 事项 | 原判断/尝试 | 复核与修正 | 当前边界 |
|---|---|---|---|
| G7 receiver-exit USB 恢复 | candidate012 r3 的 51 字节 HELLO_ACK `send_status=0`，初步怀疑旧 dTD completion/发送缓冲区所有权 | 新的 EP1 IN 诊断显示对应 dTD 长度 51/51、残余 0、token `0x8000`、completion status 0、匹配标志 `0x1f`；但主机 39 次读取仍为 0 字节。之后同构建无 JTAG 的普通 CDC 重连认证 141 帧/1,130 包并再次回到 `WAIT_HELLO`。因此“普通重连不可用”不成立，receiver-exit 的实际主机接收边界仍未定位 | receiver-exit 单轮失败；20 轮和物理拔插批次未启动。dTD completion 不等于 Windows CDC 应用层收到，G7 未通过。详见 `report/g7_candidate012_tx_ownership_board_20261011.md` |
| KX41 串口采集 | 首次等待错误完成标记 `KECCAK_SX4_BENCH_DONE`，出现不完整标记 | 对照固件输出修正为 `KX41_BENCH_DONE`；采集器/严格 parser 回归 13/13 通过；software、hardware 和 timeout fallback 三个板测窗口各完成 60/60 KAT，硬件窗口耗时为软件的 88.6% | 独立 KX41 候选，不代表视频固件集成；内部 Keccak STATE/OUTPUT 清零未读回。详见 `report/keccak_sponge_x4_capture_fix_20261011.md` |
| M02 摄像头冷启动与缺席处理 | 需要多轮现场上电及完整断电拔除摄像头模组 | 用户逐轮确认 20 次整板断电/上电后的 JTAG 配置通过 20/20；完全断电拔除模组后 fail-closed 通过，随后恢复模组并重新上电 | 只覆盖 JTAG 加载后的配置和无模组 fail-closed；SD/Flash 独立启动、DVP/JPEG 实拍未测。详见 `report/m02_sensor_reset_board_20261011.md` |
| 比赛材料状态 | 旧评估仍记录板卡未枚举、KX41 单向量和截止时间未知 | 新鲜记录确认 COM16 `03FD:7020` 与 candidate012 普通 CDC 重连；KX41 已更新为 60/60 三窗口；赛事协办方赛程页和高校通知列出 2026-11-04 18:00 截止 | 报名资格、AMD 赛道最终规则、报告/视频细则、仓库公开与许可证授权仍需官方材料/权利人确认；没有把工作稿称为正式提交材料 |

材料改进：补充 `skill/eyepqc-fpga/README.md`，把构建 hash、implementation timing、DMA/DDR 所有权和 G7 失败分析整理成可复核案例；目前只证明案例与本仓库证据一致，未声称经过外部团队迁移验证。
