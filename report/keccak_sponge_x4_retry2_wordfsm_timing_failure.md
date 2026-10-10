# Keccak Sponge x4 retry2 时序记录

retry2 的 100 MHz 系统完成布局布线，但仍未满足 setup 时序。Vivado 因 max slack 为负停止，未导出 XSA；本版本不可进行实板试验。

- WNS/TNS：-0.811 ns / -830.003 ns；setup 失败 3609/63313 endpoints。
- WHS/THS：0.087 ns / 0.0 ns；hold 失败 0。
- 资源：LUT 27759，FF 21350，Slice 8654，BRAM/DSP 0/0。DRC 错误/严重告警数：0。
- 最差路径：`system_i/keccak_0/inst/lane_q_reg[0]_replica/C` → `system_i/keccak_0/inst/state_q_reg[3][500]/D`，10.716 ns（逻辑 2.231 ns，布线 8.485 ns），10 级；单元：CARRY4=1 LUT2=1 LUT4=1 LUT5=2 LUT6=4 MUXF8=1。布线约占该路径79%。

相较 retry1，WNS 从 -7.498 ns 改善到 -0.811 ns，setup 失败端点由 37072 降至 3609。关键路径现从 `lane_q` 经 lane/input byte mux 和 `build_absorb_word` 到 state bank，主要延迟在路由。retry3 会在 word builder 与 state 更新之间加 64-bit 寄存器边界，将吸收字的构造和 state/core 选择拆成两个周期；这会增加少量状态机周期，必须保留 100 MHz 约束并重新验证功能与完整路由。

XSim 六种长度测试和 60 个 ACVP 向量的 120 次 host-MMIO mock/fallback 测试已通过，但并不证明当前 RTL 在板上运行或 Decaps 加速。retry2 的 timing/utilization/DRC/log、build-start 哈希及对应六个源文件字节副本都保存在 `build/parallel_20261010/C/sx4_retry2_wordfsm/`。
