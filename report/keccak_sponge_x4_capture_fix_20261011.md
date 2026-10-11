# KX41 串口采集修复与候选固件复核

**状态：离线构建、清单复核和采集器回归测试通过；全 60 组实板测试仍未执行。** 新候选没有替代硬件验收证据，也不与历史 tcId 76 单向量板测合并。

## 修复内容

旧采集器在 XSDB 成功退出后最多再等待 1 秒；而 XSDB Tcl 已经启动固件并断开连接，固件仍可能继续输出三窗口的 60 组 KAT。该时间窗会截断 UART 日志，导致完整板测结果无法可靠归档。现在采集器在 XSDB 成功退出后持续读串口，直到固件输出 `KECCAK_SX4_BENCH_DONE` 且 XSDB 已退出，或达到整体串口超时；XSDB 非零退出仍立即结束并判失败。

新增的模拟串口测试覆盖“XSDB 成功退出后延迟收到完成标记”和“XSDB 非零退出立即终止”两种情况。解析器原有 11 项测试与采集器新增 2 项测试共 **13/13 通过**。

## 新候选离线证据

- 构建目录：`build/kx41_capturefix_20261011/`。首次长路径尝试留下在 `build/parallel_20261011/C/firmware_sx4_retry3_board_60kat_capturefix/`；HSI 生成 BSP 时目标路径达到 261 个字符并失败。该目录保留作故障记录；新候选使用较短的全新路径重新构建，没有复用失败输出。
- ARM ELF SHA-256：`c978de597bbc9eaea63a686171d706d5adabed97e50ab9f66eff7bc9d1c472f9`，大小 564520 字节。
- 候选 `build_manifest.json` SHA-256：`23f1e5fdcffc626be6e2231a5e6b89552964f4bd1d42e5d2fa5f03571acef8c1`。
- `--verify-only` 通过，复核 715 项输入哈希；匹配 XSA SHA-256 `ed634c6d480de36c16af64962093069cc120e04af5b38498978e210bf404318d`，最终布线 WNS `+0.029 ns`、WHS `+0.082 ns`，失败端点为零。
- 测试仍覆盖 keygen 25、encapsulation 25、decapsulation 10 个向量，并计划在软件、KX41 硬件、强制超时回退三个窗口逐项比对输出。普通硬件窗口的任何软件/超时/错误回退都会使 parser 拒绝验收。

## 硬件边界与下一步

本轮只构建固件、校验文件哈希并运行本地单元测试；没有打开 UART、XSDB、JTAG，也没有向 FPGA 或启动介质写入内容。最新 Windows present-only 枚举可见 USB-SERIAL CH340（COM14），仍未发现目标 `03FD:7020` CDC 或 Xilinx/Digilent JTAG，因此全 60 组板测不能开始。

待 JTAG 与 USB CDC 同时恢复枚举后，使用本目录执行严格采集：先 software，再 KX41 hardware，再 forced-timeout；三窗口都要包含完整 60 组且通过 parser。板测需独占串口/JTAG，保留原始 UART/JTAG 日志与候选 manifest。新的离线清单位于 `build/kx41_capturefix_20261011/build_manifest.json`；旧候选 `firmware_sx4_retry3_board_60kat_strict2` 及其构建身份保持不变。
