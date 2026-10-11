# G7 candidate014 安全 HELLO_ACK 重试离线候选

日期：2026-10-11。状态：固件构建、离线测试、候选哈希预检和批测 dry-run 均通过；尚未下载到板卡，`board_validated=false`，不构成 G7 实板验收。

## 修正内容

candidate012 的 receiver-exit 批次出现两次 HELLO_ACK 超时。candidate013 加入缓存 ACK 重放和主机重试后，审查发现 ACK 只收到部分 USB 帧时再次发送会把新数据拼入旧解码缓冲，因此 candidate014 增加了保守边界：

- 固件只在 `WAIT_KEM` 阶段收到与缓存 HELLO 完全相同的消息时重放同一缓存 ACK；不会生成新随机数或更改会话状态。不同 HELLO 仍被拒绝。
- 主机最多补发两次原样 HELLO，每个 ACK 等待窗口为 3 秒。若超时后解码器仍有未完成 USB 记录，主机不重发并按超时失败，避免将新 ACK 拼入残帧。
- 主机收到 ACK 后等待 board-finished 时，只忽略与已验证 ACK 字节完全相同的迟到重复记录。
- 批测 runner 仅从精确匹配 `trial_NN_tryNN.json` 的尝试记录分配 try 编号，诊断 JSON sidecar 不再导致编号跳跃。

这是针对完整 ACK 丢失的容错，不是已确认的 USB 根因修复。半帧响应仍会安全失败，实际恢复率须由实板验收确认。

## 构建与离线验证

- 构建变体：`g6-secure-buffer-cleanup-candidate014-safe-hello-ack-retry-v1`。
- 本机工作区：`build/vitis/g6_secure_cleanup_20261011_candidate014_safe_hello_ack_retry`。
- ELF SHA-256：`5ea135b67daee97fa4b30cf0da552a538461fbfbde8c28acf7a6d44c064a34c7`。
- Manifest SHA-256：`4396e274d65db68b706cd0eb2682602d76917db028ebbea5cf26521c6a27c35e`；XSA SHA-256：`46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`。
- Vitis 2026.1 ARM GCC 构建通过；`g6_board.py --verify-only` 复核 197 项哈希；`run_g7_batch.ps1 -DryRun -Attempts 20` 和 ETW 一键脚本 `-Plan` 均通过。
- 25 项 G6 离线测试和 9 项 G7 batch runner 测试全部通过。覆盖真实 `g6_usb.c` 分支 C harness、同 HELLO ACK 重试、重复 ACK 处理、收到半帧时禁止重试、G6 控制/清理路径及 runner sidecar 编号回归。

## 后续门禁

candidate012 的 13 个通过轮不能折算到 candidate014。candidate014 仍需新板上短基线、ETW/AP0 单轮；单轮通过后从零完成 20/20 receiver-exit，再单独完成 20/20 物理 USB 拔插。当前没有访问或写入板卡、SD、Flash 或 eFuse。
