# G7 candidate011 接收进程退出实板诊断

日期：2026-10-11。结论：candidate011 的首个 receiver-exit 单轮在恢复握手时失败；加入无载荷主机诊断并重新构建后，又在新 receiver 建立视频前复现 HELLO_ACK 超时。两次均 fail-stop，G7 不通过；20 轮批次和物理 USB 拔插批次均未启动。

## 板测前与基线

- 用户重新插拔 JTAG 与 USB Slave 线后，Windows 枚举视频 CDC `03FD:7020`（COM16）和 FTDI 调试适配器。仓库只读 XSDB 检查通过，可见 APU、Cortex-A9#0 与 xc7z020；检查没有复位、下载或读写板卡内存。
- candidate011 build workspace：`build/vitis/g6_secure_cleanup_20261010_candidate011_receiver_exit_diag_final`。ELF SHA-256：`1f8ec0709104e54b74a8ade4844f0cae5e760ae711799ea16cdb0534bcff51e6`；manifest SHA-256：`e9953dcb3cd8e6a7383d1d5fa8ba8ab91d493146b76f0f9136e9429d1a987268`；XSA SHA-256：`46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`。
- 通用 `run_g7_recovery.ps1 -BaselineOnly` 在板卡访问前失败，因为该 G6 独立构建没有通用 `verify_software.py` 所需的 `software_build.json`。随后改用 candidate011 自带的 `g6_board.py`：JTAG 加载后认证握手和 2 帧 JPEG 基线通过，`jtag_load=true`，构建身份匹配。
- 为区分无数据与 framing 错误，`g6_board.py --debug-stage` 和 G7 batch 加入只记录 RX 字节数、已解 channel 计数及 decoder 缓冲头部元数据的诊断，不写出载荷或密钥。由于 manifest 绑定这些主机脚本，旧 ELF 预检正确拒绝了修改后的源；随后在新 workspace `build/vitis/g6_secure_cleanup_20261011_candidate011_rxdiag` 使用同 XSA/固定 BSP 完成新构建。新候选 `--verify-only` 197 项哈希通过，G7 dry-run 通过。

## 单轮 receiver-exit 结果

`run_g7_batch.ps1 -Attempts 1` 在一轮失败后 fail-stop。中断前主机认证解码 7 帧；新 receiver 发出 HELLO 后，在等待板端控制响应时超时。错误为 `TimeoutError: G6 control response timeout`，失败阶段记录为 `read_post_recovery_rekey_diag`。批次日志位于忽略目录 `report/g7_runs/g7_batch_receiver_exit_20261011_090352_015_a019b22d/`，主机完整结果位于相应 `data/captures/` 子目录。

板端 AP0 只读前后快照显示：

| 诊断项 | 前快照 | 后快照 / 差值 |
|---|---:|---:|
| `hello_attempts` | 2 | 3，增加 1 |
| `hello_ack_send_attempts` | 2 | 3，增加 1 |
| `hello_ack_send_status` | 0 | 0 |
| `cleanup_count` | 6 | 10，增加 4 |
| `connection_epoch` | 10 | 14，增加 4 |
| `control_errors` / `fatal_errors` / `transport_errors` | 0 / 0 / 0 | 0 / 0 / 0 |
| `rx_bad` / `rx_bytes_buffered` | 0 / 0 | 0 / 0 |

`hello_ack_send_status=0` 表示固件发送调用报告成功；它不能单独证明主机解析器收到并解码了 ACK。现有证据把失败收窄到“板端观察到 HELLO 并报告 ACK 发送成功，但主机没有得到可解码的控制响应”，仍不足以确认根因。此结果没有证明 EP1 USB IN 线上数据内容，也不能直接归因于 EP0 descriptor 回复缓冲区缺陷。

新诊断构建的单次 receiver 启动在 `start_interrupted_receiver` 阶段再次超时，尚未满足两帧门槛，也没有计为 receiver-exit 轮。主机日志记录 39 次串口读取、RX 总字节数 0、解出 control/video 记录均为 0、decoder 缓冲 0 字节，排除了收到半条记录后卡在 framing 的解释。随后只读 AP0 快照为 `WAIT_HELLO`、`hello_attempts=2`、`hello_ack_send_attempts=2`、`hello_ack_send_status=0`、`tx_ready=1`，DTR=0，`rx_bad=0`，control/fatal/transport 错误为 0，EP1 prime/ready/completion/flush 均为 0。这个快照确认固件处理过 HELLO 并报告发送成功，但仍不能确认 EP1 IN 的 DATA_TX 完成事件确实对应本次 ACK，也不能确认主机 USB 层收到数据。诊断日志位于忽略目录 `report/g7_runs/g7_batch_receiver_exit_20261011_091336_087_570b98ca/`。

## 恢复和下一步

诊断后通过 `build/restore_candidate006d_after_kx.tcl` 成功重新下载 candidate006d，成功标记经文本校验，CDC COM16 重新枚举。期间一次恢复尝试因 FTDI `FT_Write` I/O 错误中断，后续只读 JTAG 检查通过后重试成功。candidate006d 的旧 G6 workspace 未通过当前主机预检：`src/ps/src/g3_camera.c` 与其历史 manifest 不一致，因此没有把该旧 workspace 的 no-JTAG 视频尝试计为验收，也没有声称恢复后视频已复测通过。板上原 SD 卡、Flash 与 eFuse 未改动。

下一步核查 EP1 IN `DATA_TX` 回调、`tx_ready` 的复位/释放来源，以及 DTR 低电平时的端点 quiesce/rebuild 顺序；给诊断记录增加能够关联到本次 ACK 的端点完成证据，再离线测试、更新 manifest 并构建新候选。修复或原因收敛前不重复跑 20 轮。新单轮通过后才可开始独立 20 轮 receiver-exit，物理 USB 拔插 20 轮仍等待前序门禁通过。
