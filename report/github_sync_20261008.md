# 2026-10-08 开发进度与 GitHub 同步

本次整理发布主机演示、录像导出、G0 验收工具、G7 恢复脚本，以及隔离的 Keccak 和摄像头/DMA 恢复候选实现。核心视频链路已有实机证据；G0/G7 整体和生产安全仍未验收。此次同步只执行电脑端检查，没有操作板卡或写入 SD/Flash。

## 已完成与证据边界

| 范围 | 已有结果 | 仍缺的验收 |
| --- | --- | --- |
| 实机演示 | 15 秒录像、换钥、Tag 拒绝后恢复、回放后重连；722/722 帧保存，MP4/AVI 各完整解码 722 帧 | 长时间录像和不同负载 |
| 接收程序异常退出 | 同一 usbfix3 构建下 20/20 次新握手恢复，无逐轮 JTAG 重载 | 不代表摄像头/DMA 故障恢复 |
| USB 物理拔插 | 严格有效 20 次，由原批次 17 次及修复后替补 3 次组成 | 不保证之后每次连接均成功；旧失败记录保留 |
| G0 | final2 临时 JTAG 启动、LED 观察、30 秒 64 KiB DDR scratch/定时器检查 | SD 独立启动、物理复位、断电冷启动后 30 分钟；M02 的 20 次摄像头冷启动另计 |
| 摄像头/DMA 恢复候选 | candidate7 的受控 camera-reset、candidate6 的 routing-stall 各有单轮通过；真实 S2MM Busy 持续到约 3 秒软件 deadline，恢复后各有 93 帧 | 同一最终构建下完整重复验收、物理摄像头故障；Busy deadline 不等于硬件 timeout IRQ |
| Keccak 加速原型 | 独立 RTL、84 组 SHA3/SHAKE 对照、AXI-Lite、PS 驱动 mock、完整 ML-KEM decapsulation 调用链 mock | 新 XSA/地址映射、板端 MMIO 与回退验收、同板基线及端到端收益 |

候选成功和失败的脱敏摘要及原文件 SHA-256 见 [验证快照](validation_snapshot_20261008.json)。原始板测、录像和构建产物保留在 Git 忽略目录；快照中的本地证据路径用于在原电脑追溯，不是 GitHub 上可下载的附件。

## 最新阻塞与实验入口

candidate7 的 routing-stall 尝试在故障触发前未取得两帧认证解码基线，批次失败。随后 22:16 的 usbfix3 基线恢复记录在 USB CDC 枚举阶段失败。22:10 的一次 CPU 快照将 PC 定位到 SDK `XUsbPs_EpQueueRequest` 的无界 ATDTW 轮询，是固件侧排查线索，尚不能单独解释枚举失败。同步前只读 Windows 检查已重新看到 COM16，但没有据此认定认证视频恢复。

`prj/build_g6_auto_recovery.py` 当前产生独立 v3 候选，加入 `prj/prepare_usb_bounded_sdk.py` 的哈希锁定 USBPS overlay：有界 ATDTW/flush 处理、失败时禁用端点、保持描述符所有权，并将 CH9 描述符发送失败从死循环改为 EP0 stall/错误返回。overlay 仅生成到新工作区，不修改 AMD 安装目录或原 BSP，也不提交生成的厂商驱动副本。v2 成功记录不能用于证明当前 v3 已通过实板验收。

下一步先恢复匹配固件的认证视频基线，再验证最终候选的 USB、摄像头和 DMA 恢复；不把不同候选的通过轮次合并成统一验收。设备私钥/随机种子仍采用开发态 JTAG 注入，可信熵源、安全存储及完整清零边界见 [安全差距](security_gap_audit.md)。

## 本次电脑端检查

- 演示 `test_demo.py`：12/12；G6 主机 `test_g6.py`：11/11。
- G0 日志验收、G6 自动恢复策略和摄像头/DMA 诊断运行器：19/19。
- Keccak RTL/AXI/驱动：4/4，SHA3/SHAKE 84 组向量全部通过。
- 完整 ML-KEM-512 decapsulation KAT：默认软件回退、硬件 mock、超时回退三条路径均通过；不代表硬件加速实测。
- USB SDK overlay/hash 与寄存器 mock：2/2。修正 mock 的端点 flush 位掩码，保留超时/复位抢占/描述符所有权判据。
- 冻结快照的 v3 候选 Cortex-A9 固件构建通过，169 项哈希预检通过（`board_accessed=false`）。复用同 XSA 的基线 BSP；已验收基线源码按原始字节保留，避免 checkout 换行转换破坏旧 manifest 的哈希绑定。此项只有编译/链接与预检，没有上板。
- 实际 Tk 演示窗口检查：`DEMO_GUI_OK`。
- 29 个 Python 文件编译检查、4 个 PowerShell 文件解析、7 个 Tcl 文件结构完整性检查通过；这些检查不执行硬件操作。
- 提交前运行仓库 pre-commit 的 M00/M10/M12/G5 离线检查，并检查暂存空白错误及凭据模式。

已有约 50 分钟长测按用户的时长例外记录，未实测完整两小时。正式提交格式、统一 Benchmark、答辩材料和整机剩余门禁见 [提交检查表](competition_submission.md) 与 [下一阶段计划](next_stage_plan.md)。
