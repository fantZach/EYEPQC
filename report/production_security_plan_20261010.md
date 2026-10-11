# 生产安全闭环计划

更新：2026-10-10。本文依据当前仓库源码和 [会话密钥与清零边界审阅](security_gap_audit.md) 制定电脑端实施与后续板级验收路线。当前 G6 是开发态协议实现；**生产安全未通过**。本文没有验证硬件熵源、密钥存储、启动链、JTAG 生命周期或全域清零，也不构成安全认证。

2026-10-11 的电脑端 profile 与软件 DRBG 进展见[实施记录](production_security_profile_20261011.md)：生产宏下已排除开发 JTAG mailbox 与 host-seed 随机路径，并接入 HMAC_DRBG-SHA-256 与外部熵/provider fail-closed 接口；真实 provider、板端熵源、密钥保护及读回门禁仍未完成，状态仍为**生产安全未通过**。

## 当前实现能证明的边界

| 安全域 | 源码中已有行为 | 缺口与结论 |
|---|---|---|
| 会话密钥与状态 | `src/ps/src/session.c` 用 volatile 写清会话 transcript hash、视频/控制 key、nonce prefix、session ID、序号和 replay 状态；派生与 HMAC 的若干临时状态也会清理。 | 只覆盖显式列出的对象。PS cache、栈/堆副本、寄存器、异常转储、调试访问和复位/掉电过程没有全域读回证据。`last_transcript` 是保留状态，不能按全结构清零描述。 |
| ML-KEM 长期私钥与随机种子 | `src/ps/src/g6_usb.c` 从 `g6_sk_load`/`g6_seed_load` 复制到静态 `private_key`/`random_seed`，随后清 mailbox；输入校验失败时清静态副本。 | `prj/provision_g6_jtag.tcl` 明确是开发态，通过 JTAG 写入 1632 字节私钥与 32 字节主机生成的 seed。成功后的正常断连、STOP、REKEY 和 fail-closed 路径保留静态长期私钥/seed；源码没有生产 provisioning 或受保护持久化实现。 |
| 板端随机服务 | `board_random()` 计算 `HMAC-SHA-256(random_seed, host_random || counter)`，并清理其 40 字节输入缓冲。 | 该实现以注入的 seed 为根，没有从源码证据中发现被调用的板端噪声源、熵估算、启动/连续健康测试或 DRBG。不能据此确认此板不存在硬件噪声源，也不能把主机 seed 说成板端可信熵。重启后的 seed 唯一性和反回滚也未建立。 |
| ML-KEM 和会话临时值 | 解封装共享秘密、Finished、nonce、HMAC/HKDF状态以及 session key 有显式清理。2026-10-10 的独立安全候选新增 CPU-local control 缓冲统一擦除，并在不再使用后擦除 HELLO/ACK/body_ack。ML-KEM 源码有中间对象 zeroize hook，见[实施报告](security_cleanup_20261010.md)。 | 这批实现只覆盖明确对象与路径。`tx` 的 USB 异步所有权、编译器 spill/寄存器、优化后的全调用图和硬复位过程未获全域清零证明；HELLO/ACK 是公开协议数据，不代表真实秘密域已全覆盖。 |
| PL AES-GCM | `src/ps/src/g3_camera.c` 暴露 `g3_usb_zeroize()` 写 GCM 控制寄存器；每帧加密前、帧发送后以及 G6 STOP/REKEY、断连和 fail-closed 路径会调用。 | 控制寄存器命令与已有离线/局部证据不能证明全部寄存器/内部流水、异常中途复位和总线副本已清。当前没有 PL 全密钥状态读回验收，也没有侧信道/故障注入评估。 |
| 摄像头明文与 DDR | G3/G6 用 `g3_frame` 保存 JPEG，`g3_sealed` 保存加密输出；DMA 重置、缓冲所有权和边界保护已实现。 | 正常 STOP、断连或清除 GCM key 不会对完整 `g3_frame`/`g3_sealed` 作全区写零。DMA/cache 停止与维护后的逐地址清零读回没有实现/证明。DDR 还有栈、堆、BSS 和共享 mailbox 等副本域。 |
| USB 软件和 DMA 元数据 | `src/ps/include/usb_recovery.h` 对停止后的 dTD/QH 做 invalidate、清零和 flush，再重建端点；恢复路径管理环与所有权。 | 该操作是恢复正确性措施，不等于所有接收/发送数据、控制缓冲、主机控制器、USB PHY 或线缆副本均安全擦除。硬件卸载、缓存一致性和描述符逐项读回未形成安全验收。 |
| 主机进程 | `src/host/handshake.py` 的 `HostSession.close()` 覆盖 bytearray 视频/控制密钥后释放字段；2026-10-11 后续改动让 M09 shared/keygen 输出及 HKDF PRK/T1/T2/material 使用可覆写缓冲，成功/重放拒绝/异常退出均清本次拥有的 coins/shared/material；G6/M10 调用方也清 coins，离线 peer 清 decaps shared/material 与私钥缓冲。 | 这是应用可控缓冲的 best-effort 清理。Python `bytes`、`hmac.digest`、ML-KEM/native 扩展、密码库、JPEG/GUI/崩溃转储和 allocator 副本仍没有全面擦除保证；不能把它描述为 host 全进程清零或抗内存取证。 |

现有证据仅支持“若干对象有显式清理路径”：M10 离线/既有证据覆盖指定会话对象和 PL 清除命令；G6 软件集成用例覆盖受控会话行为；candidate006d 同构建 40 轮是 USB/摄像头/DMA 恢复证据。它们都不是设备安全认证、全内存清零或生产密钥验收。具体阶段与状态见 [验收矩阵](acceptance_matrix_20261009.md)、[软件阶段交付](software_ready.md) 和 [006d 报告](g7_candidate006d_acceptance_20261010.md)。

## 最小实施路线

### 1. 固定产品威胁模型和器件事实

先由项目负责人明确设备生命周期、攻击者可否接触实物、是否要求断电后保密、RMA/返修策略、是否接受主机参与，以及一机一钥或批量共钥的要求。对实际核心板版本核对原理图、芯片完整料号、启动配置、PS/PL 资源和可用熵接口；当前源码与仓库资料没有确认可访问的板端熵接口。若无法在实际器件和连线中建立可测的噪声源，不得把 Zynq 系列名或 CPU 时钟、计时器、主机随机数推断为设备熵源。

### 2. 建立随机服务并 fail closed

把现有 `board_random()` 替换为单一随机服务 API，并区分原始熵源、健康测试、调理、DRBG 与调用者。按所选源的性质完成熵评估、启动测试、运行时健康测试、错误锁止、重播种和状态恢复设计；熵/健康检查失败时，不发送 HELLO_ACK、不执行 ML-KEM 密钥操作，也不继续旧会话。确定性测试应固定标准向量并注入常量源、重复源、截断源、熵不足、健康测试故障和重启/计数器回退。统计随机性测试不能代替熵源评估。

NIST SP 800-90B 规定熵源设计原则、熵评估与健康测试，并用于构造 SP 800-90A DRBG / SP 800-90C RBG；实现时应从对应正式文档及其当前 errata 建立需求追踪，而非只引用随机性测试结果：[SP 800-90B](https://csrc.nist.gov/pubs/sp/800/90/b/final)、[SP 800-90A Rev. 1](https://csrc.nist.gov/pubs/sp/800/90/a/r1/final)、[SP 800-90C](https://csrc.nist.gov/pubs/sp/800/90/c/final)。

### 3. 替换 JTAG 注入，定义密钥 provisioning

先选择并记录可部署的密钥保护方案，再改造 G6 接口：量产私钥生成/导入主体、设备身份绑定、公钥登记、密钥轮换、版本/反回滚、读取控制、故障恢复、返修注销和销毁均要有明确流程。`provision_g6_jtag.tcl`、mailbox `g6_sk_load`/`g6_seed_load` 只保留在受控开发/测试构建中；生产构建不得接受该 mailbox 或留有可绕过认证的调试接口。

不要将 Zynq 启动安全特性直接等同于 ML-KEM 私钥安全存储：AMD Zynq-7000 文档描述 RSA 公钥哈希、启动认证及 AES 启动密钥等 SoC 启动功能，尚未证明能直接存储/隔离本项目 1632 字节私钥。JTAG 禁用和部分 eFuse 配置是生命周期决策，AMD 文档指出相关选项可能永久生效并影响 RMA；仅完成器件/返修/恢复方案审查后，另行安排受控器件验证，不在本计划中编程 eFuse：[AMD UG821 Secure Boot](https://docs.amd.com/r/en-US/ug821-zynq-7000-swdev/Secure-Boot-Support)、[AMD UG585 PS eFUSE](https://docs.amd.com/r/en-US/ug585-zynq-7000-SoC-TRM/PS-eFUSE-Settings)、[AMD UG585 JTAG/debug](https://docs.amd.com/r/en-US/ug585-zynq-7000-SoC-TRM/JTAG-and-Debug-Considerations)。

### 4. 定义秘密清零矩阵并实现有序清理

建立逐对象清单：长期私钥与 seed/DRBG 状态、ML-KEM 解封装内部值、会话/派生 key、协议控制缓冲、PL GCM key/nonce/state、摄像头 JPEG 与加密暂存、USB payload/descriptor/ring、DDR mailbox、host key/帧缓存和异常日志。每项记录创建点、最后使用点、共享者、cache/DMA 所有权、清零函数、屏障/cache 维护和失败处理。实现停 DMA/USB 并确认 idle → 清消费者与共享缓冲 → cache clean/invalidate 与内存屏障 → 清 PL/PS 对象 → 释放所有权的有序流程；失败时停发并保持隔离，不能在 DMA 仍拥有缓冲时写零。

测试每个正常及异常退出分支：STOP、REKEY、认证/格式失败、DMA 错误/超时、USB reset/DTR/拔插、软件超时、冷启动、看门狗/异常复位和电源中断。开发阶段可用 JTAG 读回指定 DDR/寄存器作辅助证据，但其结果不能证明量产调试口关闭后的全部片上副本已清，也不能覆盖模拟侧信道。

## 验收门禁

1. **源码与构建**：生产 variant 中无 JTAG secret mailbox、开发私钥样本和测试 key；随机 API 调用链、密钥清单、清理调用路径有源码/反汇编复核；构建清单绑定唯一 XSA、ELF、FSBL、BOOT.BIN 和来源 hash。
2. **随机服务**：来源和熵主张有实际板型依据与源评估；启动/持续健康测试和重播种实测通过；故障注入均 fail closed；冷启动/复位不复用状态。没有可信熵源时门禁失败，不进入密钥测试。
3. **密钥生命周期**：测试密钥通过选定的生产 provisioning 流程写入并完成公钥身份核验；未授权读、调试路径、错误认证、升级失败、复位、轮换、RMA 和销毁按预期拒绝/恢复。任何永久 fuse 操作需另有批准的器件方案与审计记录。
4. **清零读回**：每个列明内存段按实际 ELF linker map 定址；停止 DMA/cache 所有权后写零并读回，覆盖 normal/error/STOP/REKEY/reset/USB/DMA 失败分支。PL key/nonce 状态提供可审计的测试见证；不能观测的内部状态明确列为残余风险，不能用模拟结果代替。
5. **产品评估**：明确 secure boot、JTAG 锁定、软件升级、访问控制和物理攻击/侧信道范围；独立审阅威胁模型、故障注入结果和残余风险。只有以上条件及目标部署环境的专项评估完成后，才可更改“生产安全未通过”的状态。

截至 2026-10-10 本计划初稿形成时，仅完成源码审阅和电脑端计划。随后独立实施的 CPU-local 临时协议数据清理、候选构建和边界见[安全清理实施报告](security_cleanup_20261010.md)。这不改变“生产安全未通过”：可信板端熵源、生产 provisioning、长期密钥保护、DMA共享明文缓冲/USB描述符有序清理，以及PS/PL全域清零读回仍未闭环；未操作启动存储或 eFuse。
