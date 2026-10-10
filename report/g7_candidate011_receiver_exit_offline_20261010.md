# G7 candidate011 接收端退出恢复离线修复记录

日期：2026-10-10

结论：candidate011 修正了清理失败仍被计作正常 USB 断连的固件路径，并给下一次 receiver-exit 板测增加前后 HELLO/ACK 诊断快照。离线测试和 ARM 构建通过；本候选没有上板，G7 接收端退出恢复仍未验收。

## 修复内容

`retire_disconnected_session()` 现在返回清理结果。只有 `secure_cleanup()` 成功时才清除旧会话、回到 `WAIT_HELLO` 并增加断连计数。清理失败会保留该次发送状态、resume 状态、USB ready 和连接 epoch，将 transport 错误计数加一并进入 `FAULT`；不会增加正常断连计数。发送路径只采样一次 ready/epoch，并将同一组值用于分类和诊断，避免诊断记录与分类条件取自不同瞬间。无视频发送的断连事件用 `UINT32_MAX` 表示 send 未尝试。

`run_g7_batch.ps1` 在终止旧 receiver 后、启动新 receiver 前读取一次只读 AP0 诊断；新 receiver 正常退出或超时终止后再读取一次。新 helper 只读取 ELF manifest 所属的 116 字节 `g6_rekey_diagnostic`，校验稳定序列、ABI、构建身份及范围，不读取 packet payload 或 key。每轮记录 HELLO 与 ACK 调用计数差值和最后 ACK 发送状态。成功轮要求主机侧新会话/认证帧通过，同时板端观察到新的 HELLO 与 ACK 发送调用且发送状态为 0；发送调用成功本身不替代主机侧握手通过证据。超时轮会先停止该轮 recovery receiver，再保存诊断快照并按失败停止。

## 离线验证与构建

| 项目 | 结果 |
|---|---|
| G6 cleanup、receiver-exit 源码 harness、G7 batch、Tcl reader 及新诊断 helper | 24/24 单元测试通过 |
| ARM candidate011 build | `G6_AUTO_RECOVERY_BUILD_OK` |
| G6 host preflight | `G6_PREFLIGHT_OK hashes=197 board_accessed=false` |
| manifest 与外部工具源校验 | `MANIFEST_VERIFY_OK checked=197 external_hashes=5 board_accessed=false` |
| G7 batch dry-run | 通过，`jtag_reload_during_trials=false` |
| manifest `board_validated` | `false` |

构建目录为 `build/vitis/g6_secure_cleanup_20261010_candidate011_receiver_exit_diag_final`。variant 为 `g6-secure-buffer-cleanup-usb-bounded-candidate011-receiver-exit-diag-v1`。`g6_usb_manifest.json` SHA-256：`e9953dcb3cd8e6a7383d1d5fa8ba8ab91d493146b76f0f9136e9429d1a987268`；ELF SHA-256：`1f8ec0709104e54b74a8ade4844f0cae5e760ae711799ea16cdb0534bcff51e6`；map SHA-256：`8572dd017d173cb23e86f3524df2023215c5639e32818f1d649d27605cb98a16`。

## 尚未验证

本轮没有执行 JTAG、USB CDC 或板卡操作。最新 Windows PnP 查询没有看到目标 `03FD:7020` CDC 设备或 Xilinx/Digilent JTAG 项，因此没有运行 candidate011 的 board trial。candidate010 的 HELLO_ACK 超时仍是失败记录；candidate011 只修复清理结果和诊断门禁，尚未证明能解决该握手超时。

下一步先恢复目标 CDC 和 JTAG 枚举，以 candidate011 完成一个 receiver-exit 诊断试次，检查板端 HELLO/ACK 计数变化、ACK 状态、主机新会话和认证视频，再决定是否启动独立 20 轮批次。该门禁通过后，才进行同构建物理 USB 拔插 20 轮。
