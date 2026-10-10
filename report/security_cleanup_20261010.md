# G6 临时协议数据清理实施记录

日期：2026-10-10。本文记录一项电脑端安全候选变更及源码审阅结果。**生产安全仍未通过**；候选没有上板，也没有证明设备全域秘密清除。

## 变更范围与对象边界

`src/ps/include/g6_control_dispatch.h` 提供 G6 主循环与宿主 C harness 共用的 control dispatch。G6 的 1036 字节 CPU-local 栈缓冲在声明时初始化为零；当 USB API 返回无输入时，dispatch 立即返回，不扫描或擦写该缓冲。每次非空消息在 handler 返回后清整个固定容量；take 错误（包括 API 已写部分字节后报错）、超长返回和 handler 失败也会先清整个容量，再由主循环进入既有 fail-closed 处理。

`src/ps/src/g6_usb.c` 另有三处生命周期收紧：HELLO_ACK 的局部 `body_ack` 在 encode/send 成功或失败后都清理；KEM 消息处理完后，无论解封装/session 建立状态如何都清理已不再使用的静态 `hello` 与 `ack`；STOP/REKEY、disconnect 和 fail-closed 也清理握手缓存。`session.c` 原有关闭路径继续清会话 key 和状态，保留 `last_transcript` 防重放语义。

| 对象 | 本轮处理 | 结论与保留边界 |
|---|---|---|
| `control[1036]` | 初始化为零；处理任何非空取件后擦完整个容量，包括 take 部分写入失败、长度异常、handler 失败；空闲返回不重复擦写。 | 有实际共用 dispatch 的 C harness 覆盖。它是 CPU 本地控制消息副本，不能据此声称 USB ring、CDC 接收记录或主机副本已清。 |
| `body_ack[36]`、`hello[48]`、`ack[48]` | 前者在 HELLO_ACK 构造/发送后清；后两者在 KEM/session 消费后清，并在 STOP/REKEY、断连、fail-closed 时清。 | 它们是公开握手数据/随机挑战暂存，不是长期密钥；这项改动减少临时协议数据残留，不代表新增了板端熵或秘密清零能力。 |
| `shared[32]`、`finished[44]`、nonce、session 派生状态 | 原来已有显式清理；本轮保留并检查其调用顺序。 | 仅证明源码与目标候选中所列对象有清理路径，不证明寄存器、编译器 spill 或异常复位中的副本全部清除。 |
| `private_key[1632]`、`random_seed[32]` | 正常 STOP/REKEY、disconnect、fail-closed 不清除。 | 它们维持开发态设备密钥/seed 并支持重连；擅自在会话关闭时擦除会破坏既有重握手语义。生产 provisioning、受保护存储、轮换和销毁仍缺失。 |
| `session.last_transcript`、`random_counter` | 未改变。 | `last_transcript` 继续用于防重放；随机计数器不是密钥，也未建立持久化/反回滚语义。 |
| USB `tx`、G3 `g3_frame`、DMA/USB描述符与 GCM 内部状态 | 未修改。 | `tx` 的端点发送完成所有权与 G3/DMA缓冲清理时序需要进一步验证。未确认消费者停止前不擦共享缓冲；现有 GCM clear 命令不等于 DDR/USB/寄存器全域读回。 |

源码实施阶段没有修改 provisioning/mailbox 输入、manifest 冻结输入或旧的 006d 构建产物。后续有限实板回归由根代理串行执行，未写启动介质或 eFuse。候选 007 使用独立目录，不继承 006d 的板测通过结论。

## 验证与候选构建

`sim/tb/test_g6_control_dispatch.py` 编译并运行 `sim/tb/test_g6_control_dispatch.c`。C harness 直接包含 G6 实际调用的 `g6_control_dispatch.h`，覆盖正常消息、handler 失败、take 部分写入后失败、无输入空闲返回，以及超容量长度。前四类分别核对 handler 的输入/调用次数和清除后的整个缓冲区；空闲路径用哨兵值验证没有重复全容量擦写。桌面系统 Python 的命令 `python -m pytest -q sim/tb/test_g6_control_dispatch.py` 结果为 **1 passed**。仓库 `.venv` 未安装 pytest；在该环境可复现的入口是：

```powershell
.venv/Scripts/python.exe -c "from sim.tb.test_g6_control_dispatch import test_g6_control_dispatch_real_header_harness; test_g6_control_dispatch_real_header_harness()"
```

独立 ARM 固件候选位于 `build/vitis/g6_security_cleanup_20261010_candidate007`。它以 candidate006d 已固定 BSP 快照为复用来源，复用相同 XSA（SHA-256 `46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`），采用 G6 USB bounded/auto-recovery builder 并纳入本轮 helper/harness 源码哈希。为让 builder 接受新的 G6 源码，本地 ignored build 目录中另生成了候选专用 base manifest；它只更新该候选的 `g6_usb.c` 内容哈希，**不是**原始 accepted manifest，也不改变 006d 的身份。

目标构建结果：`build_g6_auto_recovery.py` 输出 `G6_AUTO_RECOVERY_BUILD_OK`；独立 verify-only 哈希核验输出 `VERIFY_ONLY_OK checked_entries=183 board_accessed=false`。候选 `g6_usb.elf` SHA-256 为 `4eac755e256796fd0b2ed69ba73ced43bcbc4068f4d3554772916297b5d2f9d6`。对本候选目标对象的 ARM 反汇编抽查确认 `main` 在 `usb_cdc_take_control` 后对 1036 字节栈缓冲存在写零指令循环；空输入分支在该循环前返回。`eye_mlkem_dec` 位于 `8_m09_mlkem.o`（符号范围 `0x73c8–0x7693`），能看到被内联的 `memset` 清理代码。此项只覆盖所检查的目标对象和有限代码路径，不是全调用图、全内存或上板证据。

之后根代理将同一 ELF 临时加载到板上完成两次约 3 秒会话回归：各解出 143 帧（47.611 fps）与 141 帧（47.267 fps）；错误 Finished 被拒绝，drain-stop 与 bounded-control-write 检查通过，第二个 session 的 `key_changed` 布尔为 true。此次未测 DTR 重连，board counters 不可用。原始运行 JSON 同时含 session id 与 transcript 指纹，未复制这些值；脱敏摘要及原始结果路径/SHA 见 [板测摘要](security_cleanup_board_summary_20261010.json)。该板测只说明 candidate007 功能回归；没有逐地址清零读回，不能证明 PS/PL/DDR/USB/DMA 清零；也没有完成 G7 新构建的 20 轮验收。

## ML-KEM 中间值源码审阅

项目 wrapper `src/ps/src/m09_mlkem.c` 将 ML-KEM-512 单编译单元包含进 G6。vendor `src/third_party/mlkem/src/kem.c::mlk_kem_dec` 在 cleanup 对 decapsulation 的 `tmp`、`kr`、`buf` 调用 `MLK_FREE`；`src/third_party/mlkem/src/indcpa.c` 对解密多项式、乘法缓存及中间多项式也有对应 `MLK_FREE`。`src/third_party/mlkem/src/common.h` 默认将 `MLK_FREE` 展开为 `mlk_zeroize` 后释放局部栈数组；`src/third_party/mlkem/src/verify.h` 在 GCC/Clang inline-asm 配置下以 `memset(0)` 加编译器 memory barrier 实现。`src/third_party/mlkem/src/sys.h` 在未关闭 asm 且使用 GCC/Clang 时定义该能力；本项目 wrapper/build 命令未见关闭 `MLK_CONFIG_NO_ASM` 或启用自定义 zeroizer。candidate007 的 `-O3` ARM 对象反汇编也观察到清理代码。

vendor 配置注释明确把这些称作对 FIPS 203 §3.3 的部分实现，并提醒编译器分配、寄存器与 spill 可能留下副本。因此后续仍需针对正式生产工具链和构建做更完整反汇编审查，结合 linker map、实机停 DMA/cache 后读回；硬复位、掉电、侧信道及不可读内部寄存器仍在证明范围之外。本轮没有改第三方 ML-KEM 源码。

## 尚未完成的生产门禁

板端可信熵源、健康测试和 DRBG/reseed 未建立；JTAG provision 仍为开发态，生产私钥持久化/隔离、身份绑定、轮换、反回滚、RMA 与销毁流程未实现；`g3_frame` JPEG 明文、USB TX/DMA 与 descriptor/ring 的所有权停止、缓存维护及读回未闭环；PL GCM 状态仅有清除命令，没有内部寄存器/流水读回证明；CPU/PS/PL 全域清零、复位异常路径与物理安全评估均未通过。不得将 candidate007 的离线构建或 harness 结果表述为板级/生产安全验收。
