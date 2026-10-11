# KX41 串口采集修复与 60 组实板验收

**状态：KX41 新候选完成实板验收；M02 探针完成 20/20 次板上摄像头传感器复位。M02 整板冷启动和无摄像头 fail-closed 仍待现场操作。**

## 采集器修复

旧采集器会在 XSDB 成功退出后 1 秒停止读串口。首次延长等待时误用了不存在的完成标记 `KECCAK_SX4_BENCH_DONE`；固件实际输出 `KX41_BENCH_DONE`。因此首个试跑等待到 600 秒并把运行记录标成 incomplete，虽然保留的 UART 文件完整。该记录未作为验收批次。

现已把真实完成标记定义为 `COMPLETION_MARKER = b"KX41_BENCH_DONE"`，采集器在 XSDB 成功后持续读到该标记，新增的延迟完成标记和 XSDB 失败测试均使用真实字符串。解析器 11 项测试与采集器 2 项测试共 **13/13 通过**。

## 最终候选与实板结果

- 构建目录：`build/kx41_capturefix2_20261011/`；运行证据：`build/keccak_sponge_x4_board/kx41_capturefix2_20261011_run1/`。
- 固件 ELF SHA-256：`3ed1f6b87c3318750a6e6f6904a8c82d33002b4b77f6747c71b8df69c37d2d17`；候选 manifest SHA-256：`961d9e869c104bb96c2be4f0cdf98e7e50d0a5864b81addc03fb6bd2b09dda76`；`--verify-only` 的 715 项哈希检查通过。
- 匹配 XSA SHA-256：`ed634c6d480de36c16af64962093069cc120e04af5b38498978e210bf404318d`，最终布线 WNS `+0.029 ns`、WHS `+0.082 ns`，失败端点为零。
- 2026-10-11 实板采集状态 `passed`，XSDB 返回码 0，耗时 10.157 秒；UART 13,009 字节，SHA-256 `458059e8bb7e01a3953e9cb8e9c3dda983e0a4f8b066eae72ff23bc703bbc525`。
- Software、KX41 hardware、timeout fallback 三窗口分别覆盖 60/60 个唯一 KAT，keygen 25、encapsulation 25、decapsulation 10。硬件窗口有 60 次硬件 absorb、182 个 squeeze block，软件/超时/错误回退均为 0；timeout 窗口 60/60 次按预期回退且 STATUS 全零，最终 STATUS 为 `0x00000000`。
- 计数器频率 `333333343 Hz` 下，software/hardware/timeout 窗口分别为 `50.106/44.391/50.678 ms`；本批硬件窗口耗时为软件的 88.6%。这只代表该独立 KX41 候选的本次 ML-KEM-512 KAT 窗口，不外推到视频工程。

新的实际板测通过可复现的严格 parser；首个错标记试跑保留为采集器缺陷记录，不并入验收。固件只临时经 JTAG 下载，没有写 SD/Flash。超时清理只读取 STATUS；没有读回 Keccak 内部 STATE/OUTPUT，不能据此声称内部数据清零。

## M02 补测与板卡恢复

M02 Explore 候选已在板上完成 20 次传感器复位探针，20/20 配置均读到 sensor ID `0x5640`、error=0；这不是 20 次整板冷启动。KX41 和 M02 测试后均已恢复哈希匹配的 candidate006d bitstream/PS7 init/ELF。最新枚举看到视频 CDC `03FD:7020` 为 COM16，KX41 UART 为 CH340 COM14。M02 的整板冷启动批次和完全断电后移除摄像头模组的 fail-closed 项仍待现场操作。
