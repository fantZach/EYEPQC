# G6 candidate 009：REKEY 后 HELLO_ACK 发送诊断

本记录说明候选 009 的三次实板运行，其中两次在超时窗口内进行只读 JTAG 诊断，一次同时观测主机接收结果。它们用于定位 REKEY 后的 CDC 发送问题，不构成 USB 恢复或双会话验收，也不证明固件根因。

## 观察到的现象

首次 `--load` 运行的两段各 1 秒会话通过，分别取得 45 帧和 46 帧。这只是短时诊断运行。随后不重新加载固件、每段设为 3 秒的运行在第一个 HELLO 等待 HELLO_ACK 时超时。超时前通过只读 AP0 DDR 诊断区观察到：固件处于 `WAIT_KEM`，最后控制类型是 HELLO，HELLO_ACK 发送调用返回 0；USB configured、DTR、TX ready 均为 1，RX ring 无缓存字节，控制、fatal、transport 错误计数均为 0。EP1 IN 的 PRIME、EPRDY、completion、flush 读数均为 0。

另一次不重新加载固件的主机观测在第一会话完成后的 REKEY、第二次 HELLO 等待中超时，并把失败定位到“主机没有收到数据”：本次失败 HELLO_ACK 等待调用了 39 次读取，累计 0 字节、无 decoder 缓存、无待处理记录；同一运行中第一 HELLO_ACK 和 Board Finished 分别一次完整读取 51 字节和 47 字节。观测包装器只计数读取结果，不记录 payload。它排除了残留视频帧头或 decoder 半包这一类解释，但不能说明 USB 线上是否发出、重试、重复或被端点按 DATA toggle 丢弃。

## 诊断快照

| 字段 | 009_02 | 009_03 host observer |
|---|---:|---:|
| phase / last control | WAIT_KEM / HELLO | WAIT_KEM / HELLO |
| 累积 HELLO / ACK send attempts | 3 / 3 | 5 / 5 |
| ACK send return status | 0 | 0 |
| configured / DTR / TX ready | 1 / 1 / 1 | 1 / 1 / 1 |
| RX buffered bytes | 0 | 0 |
| EP1 IN prime / ready / completion / flush | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| control / fatal / transport errors | 0 / 0 / 0 | 0 / 0 / 0 |
| failed ACK wait host reads / bytes | — | 39 / 0 |
| decoder buffered / pending records | — | 0 / 0 |

ACK send status 0 来自同步发送函数；发送函数在 TX completion callback 后才返回。因此它表明软件观察到发送完成回调，不等价于主机应用收到 ACK 数据，也不能据此判断主机 USB 栈是否因 toggle/重复包而丢弃数据。

## SDK 路径审阅与范围收窄

候选 ELF 绑定的 XUsbPs SDK 发送路径显示，`XUsbPs_EpQueueRequest` 在 dTD ring 中取 head，挂接并激活描述符，推进 head；当 `dTDTail != dTDHead` 时按运行中的 pipe 将新 dTD 接到 QH 并 prime。TX completion IRQ 则从 tail 起逐项检查已完成 dTD、调用 DATA_TX handler，再推进 tail。当前 `usb_cdc_send` 等待 `tx_ready`，该状态由 DATA_TX handler 置位，所以正常返回时最后一个同步发送的 completion 已被软件处理。

REKEY 清理仍会执行 `secure_tx_quiesce`、清 TX 缓冲并执行 `secure_tx_rebuild`；该 rebuild 会清 completion、重建 EP1 IN 描述符/QH、清故障标记并重新使能端点。常规 control queue 清理还会 disable/flush 数据端点、清 completion、重建方向并重新 prime OUT。由此存在一个值得 010 验证的最小化方向：当 IRQ 屏蔽后确认 TX ready、FLUSH/PRIME/EPRDY 均为零且整个 EP1 IN ring 没有 ACTIVE dTD 时，执行缓冲区清零和读回，但保留 QH、ring cursor、端点使能和 toggle；只有确有活动/取消的已安全 quiesce 路径才做 completion 清理与重建。

这是待验证的候选修复方向，不是已确认根因。当前 009 快照没有暴露每个 dTD 的活动位、head/tail 相对位置或 QH overlay 状态，因此无法证明 idle 条件，也不能从 `EPRDY=0` 单独推断 descriptor ring 与 controller 的状态一致。DATA toggle 是否被重建间接改变也没有本次证据支持。下一版应在真实 SDK native tests 覆盖 cursor 同步、所有 dTD inactive、队列残留/active 时拒绝 fast path、保持 QH/ring/toggle 的 idle path；并单独验证 quiesce/rebuild 失败关闭。物理双会话复测仍是必要门禁。

候选 010 的 ownership EPRDY 门禁由另一项 SDK policy 工作负责；probe/G6 后续集成须串行完成，并在新诊断中区分 ownership gate 及轮询结果、idle-no-rebuild 与 quiesce-rebuild 路径。009 源、ELF、reader 均保持不变。

## 构建与证据绑定

候选变体为 `g6-secure-buffer-cleanup-usb-bounded-candidate009-diagnostic-v1`。完整 SHA-256 和脱敏数值指标见同名 JSON。原始捕获及日志只通过哈希绑定；本文件及 JSON 不包含会话标识、密钥指纹、视频或 USB payload。
