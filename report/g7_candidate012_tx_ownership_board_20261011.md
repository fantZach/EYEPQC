# G7 candidate012 TX ownership 实板诊断

日期：2026-10-11。结论：candidate012 r3 的一次 receiver-exit 恢复仍失败，G7 未通过，20 轮 receiver-exit 和物理 USB 拔插批次均未启动。新增的发送所有权诊断确认本次 51 字节 HELLO_ACK 对应的 EP1 IN dTD 已报告完成；Windows 主机进程仍记录 39 次读取、0 字节。该结果把问题范围从“旧 dTD 完成被误认成新 ACK”缩小到实际 USB/CDC 主机接收边界，但不能证明 ACK 已进入 Windows CDC 应用层，也没有确认根因。

## 构建与基线

- Candidate：`build/vitis/g6_secure_cleanup_20261011_candidate012_tx_ownership_r3`，variant 为 `g6-secure-buffer-cleanup-candidate012-tx-ownership-diag-v2`。
- ELF SHA-256：`2a7a881e202c47d1ec420607e6fe3973c8e58e2f8cf85ff4b4c261e66019bc5f`；manifest SHA-256：`078c44ecd120f38b12cfb6d843a38dba9e28031c6fe0bd403a2f2e0c5e5e1eb6`；XSA SHA-256：`46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`。
- `g6_board.py --verify-only` 检查 197 项哈希通过；`run_g7_batch.ps1 -DryRun` 通过。候选不是 G7 验收构建，manifest 的 `board_validated` 仍为 false。
- COM16 (`03FD:7020`) 与 FTDI JTAG 在板测前枚举正常。JTAG 仅用于易失性固件下载和 AP0 诊断，不写 SD、Flash 或 eFuse。
- 同构建单会话认证视频基线通过：14 帧、101 个认证包。结果文件：`data/captures/g6_usb_20261011_101341_490704/result.json`。这是短时基线，不代表长时稳定性。

## Receiver-exit 单轮

恢复前的接收进程认证了 4 帧（39,463 字节、32 个认证包）；runner 未在两轮尝试之间重载 JTAG。接收进程退出后，新 receiver 发 HELLO，板端进入 HELLO 处理并调用发送函数。主机随后超时，未收到控制响应：39 次串口读取共 0 字节，decoder 缓冲为 0，因此该轮失败，不能计为通过。

| AP0 诊断项 | 前快照 | 后快照 / 变化 |
|---|---:|---:|
| `hello_attempts` | 3 | 4（+1） |
| `hello_ack_send_attempts` | 3 | 4（+1） |
| `hello_ack_send_status` | 0 | 0 |
| `tx_completion_count` | 169 | 170（+1） |
| 本次完成长度：请求 / 期望 | 100 / 100 | 51 / 51 |
| 本次 dTD：残余 / token | 0 / `0x8000` | 0 / `0x8000` |
| `tx_completion_status` / match flags | 0 / `0x1f` | 0 / `0x1f` |
| `control_errors` / `fatal_errors` / `transport_errors` | 0 / 0 / 0 | 0 / 0 / 0 |

`0x8000` 表示 IOC 位；本次 token 没有 ACTIVE、HALT、XERR 或 BUFERR，残余为 0，五项回调指针、dTD 指针、slot、连接 epoch 和请求长度匹配标志全部通过。AMD UG585 将 IOC 定义为控制器完成该 dTD 时触发 USBINT，token status 则记录控制器执行状态；这支持“设备控制器完成了关联传输描述符”的结论，但不等同于主机 CDC API 已把数据交给用户态。[AMD UG585 dTD 状态定义](https://docs.amd.com/r/en-US/ug585-zynq-7000-SoC-TRM/Transfer-Overlay-Table) 主机读取仍为零，故不能据此判定恢复成功。

原始批次记录在忽略目录 `report/g7_runs/g7_batch_receiver_exit_20261011_101410_320_756ad248/`：`trial_01_try02.json`、`trial_01_try02_rekey_before.json`、`trial_01_try02_rekey_after.json` 和 receiver/recovery stdout/stderr 日志。此前 try01 在 interrupted-receiver 达到两帧前失败，未计入恢复轮。try02 的恢复失败阶段为 `read_post_recovery_rekey_diag`，汇总为 `attempts_passed=0`。

## SDK 与 toggle 语义核查

检查本机 Vitis 2026.1 `usbps_v2_11/src/xusbps_endpoint.c`：`XUsbPs_ReconfigureEp(..., DirectionChanged=0)` 重置软件 dTD 游标、重建 QH/dTD 链并刷新 DMA 内存，没有写 endpoint control register，也没有触发 toggle reset。驱动头文件将 `TXT_BULK` / `RXT_BULK` 定义为 endpoint 类型字段，将 `TXR` / `RXR` 定义为独立的 data-toggle reset 位。

项目 `eye_usb_rearm_data(u, 0)` 的 DTR/清理恢复路径只设置 bulk/interrupt 类型，不请求 TXR/RXR；`SET_CONFIGURATION` 路径用 `eye_usb_rearm_data(u, 1)` 才请求 toggle reset。因此当前源码证据不支持“DTR 恢复误清 toggle”这一简单归因，不应只凭该假设修改 toggle 行为。USB 总线与 Windows CDC 层的实际收发边界仍需新的、能区分设备 dTD 完成、主机控制器接收和串口 API 投递的证据。

## 状态与下一步

- 单轮失败；G7 不通过，receiver-exit 20 轮和物理 USB 拔插 20 轮均未开始。
- 当前没有需要用户执行的现场步骤。先离线确认 Windows USB CDC/PnP 和串口句柄生命周期诊断是否能与主机侧 USB 事务记录关联；如缺少总线级可观测性，再评估有界的主机 USB ETW/USBPcap 采集。任何新候选都先跑基线和单轮，禁止盲目重复长批次。
- SD/Flash/eFuse 未写入；candidate012 仅临时 JTAG 下载。不得把短时基线或单次 dTD 完成上升为 G7 验收。
