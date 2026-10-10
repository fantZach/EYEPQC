# Keccak sponge x4 retry3：实现与时序结果

本轮隔离 Vivado 工程 `build/parallel_20261010/C/sx4_retry3_word_capture` 完成 fully routed，实现满足 100 MHz 时序约束：WNS **+0.029 ns**、WHS **+0.082 ns**，setup/hold 均无 failing endpoint，DRC 0 项。裕量只有 29 ps，结果仅表示离线实现门槛通过，不能当作实板运行或加速证明。

最差 setup 路径为 `watchdog_count_q_reg[3]/C` 到 `state_q_reg[1][1430]/CE`，数据路径 9.687 ns，其中逻辑 2.755 ns、布线 6.932 ns，14 级逻辑。实现资源为 26,579 LUT、21,437 FF、0 BRAM、0 DSP。精确 WNS/WHS、资源、XSA/bitstream/timing/DRC 哈希及路径记录见同名 JSON。

构建起始的六个 Vivado 输入文件均有逐字节快照，快照 hash、当前源 hash 与 manifest 一致。XSim 对六个 SHAKE128x4 长度边界 0、1、34、167、168、169 与 Python `hashlib` 对照，并通过 clear/timeout 检查；日志保存在 `build/parallel_20261010/C/sx4_retry3_word_capture/validation/xsim_boundary_test.log`。独立 ML-KEM ACVP 离线证据覆盖 60 个唯一向量（KG25/ENC25/DEC10），分别走 host MMIO mock 与 timeout fallback，共 120 次，逐次输出匹配 expected；该 mock 使用 C permutation reference，不是 PL 或板测证据。

后续板测必须使用此 XSA 与匹配 bitstream/PS7 初始化和 KX41 固件，并先重新核对哈希。即使时序通过，硬件路径、性能和 timeout 清理仍待 root 串行实板验证。
