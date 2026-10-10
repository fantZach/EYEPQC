# Keccak Sponge x4 retry1 时序失败记录

本次隔离工程完成路由，但 100 MHz setup 时序未达标。Vivado 在负的 max slack 检查处停止，因此没有导出 XSA；不得用于实板测试。当前记录只描述离线实现，不代表硬件验证。

- 目标器件：xc7z020clg400-2；Vivado 2026.1。
- WNS/TNS：-7.498 ns / -106303.891 ns；setup 失败端点 37072/63437。
- WHS/THS：0.056 ns / 0.0 ns；hold 失败端点 0。
- LUT：42034（79.01%）；寄存器：21371；Slice：12034（90.48%）；BRAM/DSP：0。DRC 检查为 0。
- 最差路径：`input_len_q_reg[3]` → `state_q_reg[3][1512]`，17.141 ns（逻辑 4.846 ns，布线 12.295 ns），27 级；估算单元 CARRY4×14、LUT6×6。

主要瓶颈是 32 位 `input_len_q` 经宽减法/比较及按字节动态索引参与 1600 位 state 更新，布线占关键路径约 71.7%。下一轮隔离改动将长度/偏移收窄为 8 位，并用 64 位 word FSM 逐拍构造整块和 padding，避免一次周期内生成整个 168 字节块。该结构会增加 absorb 周期，需用同一组 SHAKE/ML-KEM 向量验证语义并重新综合、布线；不能预设能满足时序或带来端到端加速。

完整 Vivado timing、utilization、DRC、build log 和起始源码 SHA-256 清单保存在 `build/parallel_20261010/C/sx4_retry1/`。retry1 只保存了源码哈希，没有嵌入原 RTL 字节；由于工作树之后已修改，不能将当前源码冒充为 retry1 源码。结构化数据及证据哈希见本文件同名 JSON 和该目录中的 `build_manifest.json`。
