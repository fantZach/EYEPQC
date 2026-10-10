# G6 candidate010 idle fastpath 离线记录

该记录绑定 candidate010 的构建、源文件身份、软件检查结果和一轮有限实板结果；这不是完整板卡验收。

候选由 [G6 源码](../src/ps/src/g6_usb.c)、[USB probe](../prj/usb_probe_auto_recovery.c) 和 [candidate builder](../prj/build_g6_auto_recovery.py) 构建。构建输出位于 `build/vitis/g6_secure_cleanup_20261010_candidate010_idle_fastpath_rerun`。

源码 SHA-256 为 `f6ffe9e101c3f46b0c8b73f2b8b5b9112e00bf5417fc1a66d626cad7c2c85c26`，XSA SHA-256 为 `46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`。固定构建清单 [g6_usb_manifest.json](../build/vitis/g6_secure_cleanup_20261010_candidate010_idle_fastpath_rerun/g6_usb_manifest.json) 的 SHA-256 为 `c064a826f74d35262a2ad830146fd7fcf43b61176fc5204e58d7651c9526b8c6`；ELF `g6_usb/build/g6_usb.elf` 的 SHA-256 为 `4e48ba2b0d9690f72d602d0dc1087a644f137189400bcf4ae9beb2dade5d0ff6`。清单将 `board_validated` 标为 `false`。ELF 符号检查与清单地址一致：cleanup diag 为 `0x0011b340/120`，frame 为 `0x001319c0/65600`，sealed 为 `0x00120fc0/68096`，TX 为 `0x00141c40/1472`。

root 实测包含两次 3 秒双 session PASS：第一次 `--load`，第二次不重新加载固件。两次会话均约 47 fps，视频包通过认证和分组校验，第二 session 使用新会话密钥。此后一次 `run_g7_batch.ps1 -Attempts 1` 在接收进程退出恢复时失败：恢复进程等候首个 HELLO_ACK 超时，候选 ELF仍加载在板上，没有重新 JTAG 加载。失败试次先取得 6 个已验证帧后终止原 receiver，不能算 G7 通过；该 20 轮验收仍未完成。

失败事件快照是 send status 4、resume status 0、当时 phase 4（STREAM）、USB ready 0、epoch 14、最后成功帧 7、transport error count 0。按 candidate010 的控制流推断，发送失败被归类为预期断开：意外传输错误分支才会递增并记录该计数，而诊断仍为零。该 phase 是断开发生时的快照，不是之后主循环的当前 phase。恢复主机未收到 HELLO_ACK；失败窗口没有同步读取重键诊断，因此仍不知道板端是否收到 HELLO、是否调用并完成 ACK 发送，或 ACK 是否未到达主机。

首轮 `--load` 后，在不停止 CPU 的只读 AP0 检查中，cleanup 诊断为 stage 6/result 0、route 3、DMA halted 状态无错误、GCM status 0、USB EPRDY 0/采样 1 次、cleanup path 2（quiesce/rebuild）。TX/frame/sealed 共 135,168 字节逐字读回为零，诊断在整个读回期间保持不变。范围仅限 PS DDR 中列出的三个对象；它不是全域或 PL 内状态清除证明。之后失败试次的健康快照为 status 1、fatal/control/transport 计数均 0、send status 4、resume status 0、USB ready 0、epoch 14，最后成功帧号 7；这属于退出失败后的快照，不能代替失败瞬间的收发器状态。

本轮 18 项针对性离线检查通过，覆盖 G6 实际分支清理 harness、cleanup Tcl reader、真实 probe idle fastpath harness、SDK bounded USB mock 和 recovery 测试。native fastpath harness 编译真实 probe 清理路径，并使用 pinned XUsbPs descriptor 布局；它检查 idle 清零时保留 QH、dTD 环及游标、TX enable 和 completion，并检查活动/非空队列无法证明所有权时不擦除 TX 缓冲。畸形 ring 元数据、completion 未清、QH ACTIVE/错误状态、dTD 错误和 sticky endpoint fault 均拒绝 idle fastpath。root 再独立运行其中 17 项，结果通过。

[cleanup ABI header](../src/ps/include/g6_secure_cleanup.h) 扩为 120 字节，在原有 108 字节字段后加入 `usb_ownership_eprdystatus`（偏移 108）、`usb_ownership_eprdy_polls`（偏移 112）和 `usb_cleanup_path`（偏移 116）。每轮 cleanup 会重置本轮 USB 诊断；idle 分支记录实际 FLUSH、PRIME、EPCOMPL 与 EPRDY 样本，EPRDY 采样一次。PS 诊断对象在清理回调返回后完整执行 DCache flush，以便 AP0 reader 获取本轮数据。只读脚本见 [read_g6_secure_cleanup.tcl](../prj/read_g6_secure_cleanup.tcl)。

该候选仍未完成板卡验收。虽有两次短时双 session 通过，退出接收进程后的第一轮恢复仍 HELLO_ACK 超时，因此不能宣称 G7 或 HELLO_ACK 缺陷已修复。失败路径未采集到超时瞬间的只读重键诊断快照；健康状态采样发生在主机进程退出之后。Tcl reader 检查调用者传入的 PS DDR 范围；该证据不覆盖完整 PL 内部状态或全域密钥清零。

机器可读摘要：[g6_candidate010_idle_fastpath_20261010.json](g6_candidate010_idle_fastpath_20261010.json)。
