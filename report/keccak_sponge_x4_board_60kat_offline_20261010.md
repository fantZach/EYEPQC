# KX41 60 组 ML-KEM-512 板测固件：离线构建记录

**状态：离线固件构建通过；该固件尚未上板。** 这份结果不能替代已有的 tcId 76 单向量板测，也不能据此宣称 60 组实板验收通过。

新固件将 NIST ML-KEM-512 的 60 个非 deferred 向量全部编入同一个 ARM ELF：keygen 25 组、encapsulation 25 组、decapsulation 10 组。每个向量在 software、KX41 hardware、forced-timeout fallback 三个窗口各执行一次并逐项比对 KAT 输出。正常硬件窗口逐向量要求 hardware absorb/squeeze 生效且软件、超时、错误回退均为零；软件参考窗口也要求无回退。超时窗口逐向量检查 STATUS 为零。验收范围明确不读取 Keccak 内部 STATE/OUTPUT。硬件 ID/版本日志标记窗口，并要求出现在该窗口的计时结果之前。

离线证据：ARM 固件以 `-Wall -Wextra -Werror` 构建成功；构建清单中的 715 项输入哈希复核通过；严格 UART parser 的 11 个测试通过，包含软件回退误报和硬件身份行错位的拒绝用例。ELF SHA-256 为 `78b37fc5b8410cc8e868a8a2febc833e0397d0573c5d5c043399f53556a2824d`，大小 561948 字节。匹配 XSA SHA-256 为 `ed634c6d480de36c16af64962093069cc120e04af5b38498978e210bf404318d`，布线 WNS 为 0.029 ns、WHS 为 0.082 ns，失败端点为零。

最近一次实时设备枚举未发现板卡 JTAG/USB 端点，因此本 ELF 没有进行硬件运行。板卡重新枚举后，使用此构建目录运行 `prj/run_keccak_sponge_x4_board_benchmark.py` 的硬件采集流程，完整日志应证明每个窗口的 60 个唯一 KAT 均通过，再把状态升级为实板通过。

完整固件构建清单见 JSON 清单（历史数据，本机归档）；机器可读验收记录见 JSON 记录（历史数据，本机归档）。本候选仍受 retry3 设计 29 ps WNS 裕量较薄的限制，参见 [布线记录](keccak_sponge_x4_retry3_word_capture_timing.md)。
