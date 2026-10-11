# G7 candidate013 HELLO_ACK 重试离线候选

日期：2026-10-11。状态：纯软件构建与离线验证通过，尚未下载到板卡，不能作为 G7 实板通过证据。此候选已被 candidate014 替代：candidate013 在“首个 ACK 收到部分帧后重试”的边界上缺少保护，后续版本会在残留半帧时停止重试。

## 修正内容

candidate012 的两次失败都发生在新接收端等待 HELLO_ACK 时，主机 CDC 打开成功但读到 0 字节。candidate013 加入有限、幂等的 HELLO_ACK 重试：

- 固件处于 `WAIT_KEM` 时，仅接受与当前缓存 HELLO 完全相同的重发请求，并重发已缓存 ACK；不会生成新 ACK 随机数，也不会重置会话状态。不同 HELLO 仍走原错误路径。
- 主机等待 ACK 的每个窗口为 3 秒，最多补发两次完全相同的 HELLO。后续等待 board-finished 时，只忽略与已验证 ACK 字节完全相同的重复记录。
- 批测 runner 现在只根据精确匹配 `trial_NN_tryNN.json` 的实际尝试记录生成下一 try 编号；`_rekey_before/_after` 等诊断 sidecar 不会占用尝试编号。

该策略是对丢失/迟到 ACK 的容错，不是已经确认的 USB 根因修复。主机控制器、CDC 驱动或设备端是否实际交付 ACK，必须以 candidate013 实板单轮结果确认。

## 构建与验证

- 构建变体：`g6-secure-buffer-cleanup-candidate013-hello-ack-retry-v1`。
- 工作区：`build/vitis/g6_secure_cleanup_20261011_candidate013_hello_ack_retry`（本机忽略目录）。
- ELF SHA-256：`47f05408df6d4cf307bbb2771d73eb2848d276d980684d3f2863d0f12f2d23c2`。
- Manifest SHA-256：`95130edbcfbd59b5d7e4ae5c083664769272c4729f3f465f1dad2f9b1487d450`；XSA SHA-256 与 candidate012 相同：`46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`。
- Vitis 2026.1 ARM GCC 构建完成；`g6_board.py --verify-only` 检查 197 项哈希通过；`run_g7_batch.ps1 -DryRun -Attempts 20` 通过。Manifest 的 `board_validated=false`。
- 24 项 G6 离线测试全部通过，覆盖实际 `g6_usb.c` 分支 C harness、丢弃首个 ACK 后重发相同 HELLO 并处理重复 ACK 的主机集成测试，以及现有 G6 控制/清理用例；另有 9 项 G7 batch runner 测试全部通过，含 sidecar 重试编号回归。

## 验收边界与下一步

candidate012 的 13 个通过轮只说明 candidate012；固件及源码身份已变化，不能折算到 candidate013。需要重新运行 candidate013 的板上短基线、一次 ETW/AP0 记录的 receiver-exit 单轮；该单轮通过后，再从零完成 20 轮 receiver-exit。之后另行进行 20 轮物理 USB 拔插验收。当前不要求用户现场操作，本轮没有对板卡、SD、Flash 或 eFuse 做任何写入。
