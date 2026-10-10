# G7 candidate006d 修复与恢复批次

整理：2026-10-10；实测：2026-10-09。候选 006d 的 EP0 所有权修复已完成，短时认证视频、camera-reset 20/20 与 routing-stall 20/20 均通过。**G7 整体仍未通过**：同一最终候选的接收进程退出/DTR 20 次及物理 USB 拔插 20 次尚无完整验收证据。

## 固件身份与复核

最终构建：`build/vitis/g6_auto_recovery_20261009_candidate006d`，variant 为 `g6-auto-camera-dma-recovery-usb-bounded-candidate-v4`。

| 项目 | SHA-256 |
|---|---|
| manifest | `0eb922b903f4f87b555a09cce67e928d5a910a37ece3ba359aebe055ffe28abc` |
| ELF | `e93ad4b6551bb993821a8e396d8f4c4c1f40c6bd6292247391ff129a0d9e8051` |
| XSA | `46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024` |

本轮只读审核通过 180 项 manifest 源码、BSP 输入、构建产物和 XSA 哈希检查。manifest 中的 `board_validated=false` 保留构建时声明，板测证据由下面独立记录承载。没有在本次 GitHub 整理中重新下载固件或核实当前设备在线状态。

## USB 修复

生成隔离的、固定 SDK 哈希的 endpoint/ch9/intr overlay 和私有 CDC probe。所有标准及 CDC 类 SETUP 在分派前共享 EP0 gate：有界等待两方向 FLUSH/PRIME 清空，确认旧事务释放后重建描述符；静态 Reply/TmpBuffer/line_coding 在控制器仍持有时不得改写。EP0 硬件保持启用，安全判断依据 FLUSH/PRIME，不把 disable 写操作视为释放证明。

QH 按 SDK 实际 64 字节数组处理，A9 cache line 为 32 字节。第二条 cache line 含 BPTR4 和 SETUP 字段：清理不写该行，精确 invalidate 后取最新 SETUP，只 flush 第一行。完成状态先 W1C 确认原始位，再局部屏蔽已故障 EP0 回调，其他端点继续处理。新合法 SETUP 可恢复端点 sticky；SUTW 等待有界。

标准与 CDC 类发送统一检查返回值，失败时 stall/latch；处理 SET_SEL receive 失败、line_pending 取消和新 SETUP 替代旧请求。私有 probe 与恢复 wrapper 合并为一个编译单元，避免重复链接。旧 usbfix3 源码保持其历史身份。

## 同构建实测

| 场景 | 结果 | 有效范围 |
|---|---|---|
| 短时开发态 G6 认证视频 | 471 帧、4,659,270 字节、9.9244 秒、47.3579 fps；3768 个认证包与分组包一致 | 单次短测；该 receiver 的 board_counters 为 null |
| 受控 PL 摄像头 reset/PWDN | 20/20；每次恢复后 93–94 个认证帧 | 真实 S2MM Busy 至约 3 秒软件 deadline，自动恢复后新 HELLO/会话 |
| 受控 PL routing stall | 20/20；每次恢复后 92–94 个认证帧 | 同一 ELF/XSA/manifest，故障前接收进程存活并已有认证帧 |

40 轮均验证 session/key 变化；每个场景内 40 个新旧 session 和 40 个 key fingerprint 均唯一。每批只有首次 JTAG 加载，轮间及恢复过程无重新下载。板端 capture/dropped 每轮各增 1，符合故障注入；fatal/control/transport 不增加，send/resume 状态均为 0。`camera_status` 是原始摄像头寄存器值，不能按返回码判定必须为 0。

故障侧 receiver 的 result 是 `running` 检查点；固件恢复 telemetry 出现后，harness 主动停止自己仍存活的 reader，释放 CDC 给新进程 HELLO。这一步不计为 PC 退出测试。恢复侧 receiver result 均为 `passed`，认证帧数逐轮核对。

## 证据和复现

脱敏逐轮摘要：[JSON](g7_candidate006d_acceptance_20261010.json)。审核入口：[summarize_g7_candidate006d.py](../prj/summarize_g7_candidate006d.py)。脚本固定 manifest 与两组终态目录，不扫描“最新”运行，缺失输入或任何判据不符即报错；输出只含变化布尔值、计数、仓库相对证据路径及文件哈希，不包含 session ID、key fingerprint、照片、录像或本机绝对路径。

```powershell
# 需要本地保留忽略的 build、captures 和 g7_runs；干净克隆不能复现硬件原始数据。
./.venv/Scripts/python.exe prj/summarize_g7_candidate006d.py
```

这两组是受控 PL 故障及软件 deadline 恢复，未测物理传感器拔除，也未观察到硬件 DMA timeout IRQ。旧 usbfix3 的 PC 退出/USB 拔插各 20 次及约 50 分钟长测时长例外仍为历史证据，不替代最终 006d 的回归，更不写成实测 2 小时。
