# KX41 Keccak sponge x4：一次实板基准结果

隔离的 KX41 设计已完成一次真实板卡运行。KX41 硬件 ID/版本校验通过；ML-KEM-512 Decaps tcId 76 的每次输出都与共享密钥 KAT 匹配。三个计时窗口各运行 3 次：软件参考为 1,079,494 ticks，纯硬件路径为 976,204 ticks，强制超时的软件回退为 1,078,887 ticks。硬件窗口的硬件 squeeze 计数为 9，未发生软件或超时回退；强制超时窗口发生 3 次超时回退，最终状态读数为零。

硬件窗口比软件参考少约 9.6% ticks，表明这个向量在该板上出现了小幅加速。结果只覆盖一次启动和 tcId 76，不能代表 60 个唯一 ML-KEM 向量、完整工作负载或 production integration。timeout 路径只检查了 STATUS 清零，没有读取或验证 STATE/OUTPUT 内部存储。

设计以 100 MHz 完成布线，WNS 为 +0.029 ns、WHS 为 +0.082 ns，setup/hold 均无失败端点。WNS 裕量为 29 ps，较薄，结果对实现变化较敏感。详细实现资源、路径和 RTL/KAT 离线证据见 [retry3 实现记录](keccak_sponge_x4_retry3_word_capture_timing.md)。

UART 原始记录 SHA-256 为 `c89884abb5837ee746b211a29e278f0302036062d0d182c3dff6bd9ca9c007dc`。第一次 runner 将大写十六进制硬件 ID 错判为不匹配；保留原始 capture result，并以已修正大小写处理的严格 parser 对同一 UART 字节记录重新审核，解析结果保存在 `build/keccak_sponge_x4_board/kx41_board_20261010_1936/capture_result_reparsed.json`。重解析未重新运行硬件或改变原始数据。

候选 XSA 为 `ed634c6d480de36c16af64962093069cc120e04af5b38498978e210bf404318d`；匹配 ELF 为 `c79a02bae9b836d6a22b7565232b11746db9059a882773f5b37ab135c88ce9a9`。结构化指标见 [JSON 记录](keccak_sponge_x4_board_benchmark_20261010.json)。
