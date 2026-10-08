# Keccak 加速原型验证记录

**状态：** 独立 sponge 与 Keccak-f[1600] 通过本机 XSim/`hashlib` 验证；隔离 AXI-Lite state 变体通过 XSim/OOC 综合，PS C bounded driver 与 fallback 通过 host MMIO mock。均不代表 M14 整体验收或 PS/PL 系统集成。G0–G7 门禁通过前不接入现有视频顶层或固件。

## 本次结果

- Keccak-f[1600]：5 个 Python 独立置换参考状态通过；每次 24 个仿真时钟完成。检查了 busy 时忽略新 start、clear 中止并清零。
- Sponge：SHA3-256、SHA3-512、SHAKE128、SHAKE256 共 84 组 Python `hashlib` 对照通过，覆盖空消息、rate 前后边界、整块、多块和 SHAKE 跨 rate 输出；testbench 检查输出反压时数据稳定及运行中 clear。
- 仿真：Vivado 2026.1 XSim。周期只代表 RTL 仿真。host C 基线未测，板端吞吐/频率未测，不声称加速倍率。
- 独立 Vivado OOC 综合（最终 Pi 映射源）：`xc7z020clg400-2`，0 errors；估计 8514 LUT、4933 FF、0 BRAM、0 DSP。10 ns 约束的 post-synthesis timing 报告 WNS +3.730 ns、WHS +0.262 ns、0 failing endpoints。未布局布线，不能作为板端频率或器件时序验收；综合有 3 条 warning，OOC clock-source estimation 另有警告，详见本机 `build/keccak_ooc.log` 和 `build/keccak_ooc/timing.rpt`。
- XSim 完整 sponge 用例的仿真 start-to-done 周期为 30 至 1585，平均 575（84 个测试向量、含输入输出握手和固定反压模式）。这是仿真周期计数，不含任何时钟频率假设。
- Icarus：MSYS2 Icarus 13.0 在本仓库既有 GHASH TB 和新 Keccak 编译时都返回 Windows access violation `3221225477`，没有生成可运行镜像；改由 Vivado XSim 完成功能验证。没有安装额外工具。
- 两个复现入口均已实际执行成功：`python prj/keccak_benchmark.py` 和 `python prj/keccak_benchmark.py --synth`。第二条在仿真通过后完成最终版 OOC 综合。
- AXI-Lite isolated wrapper：状态寄存器、ID/version、50 个输入和 50 个输出 32-bit word 均通过 XSim；Python 独立 Keccak 参考状态逐字相等。测试覆盖 AW/W 分离顺序、B/R backpressure、非法/非对齐地址和 CTRL strobe、busy 时 state/result访问及重启拒绝、reset/clear/watchdog timeout 清零。
- PS C 驱动和 ML-KEM adapter mock：ID/version/显式启用门禁、有界 poll timeout 后清设备、软件 fallback 通过。C 驱动默认不访问 MMIO；只有集成方在确认实验 XSA 与地址映射后显式设置 activation cookie 才会读取设备 ID/version。该 ID/version 检查不能安全探测未映射 AXI 地址。成功路径的局部返回 state 以 volatile loop 清零；硬件 clear 之外的软件栈副本也被处理。
- `python prj/keccak_axi_benchmark.py` 完整入口：4 个 unittest 通过，其中 84 个 SHA3/SHAKE 对照、AXI XSim、C mock 均成功。AXI 测试记录的 start 到读到 done 为 39 个仿真时钟，包含 AXI 操作；它不是 PS 实测等待时间或板端吞吐。
- 独立 AXI wrapper OOC 综合：Vivado 2026.1、`xc7z020clg400-2`，0 errors/0 critical warnings/21 warnings；估计 6486 LUT、6603 FF、0 BRAM、0 DSP。10 ns OOC clock 下 post-synthesis WNS +4.021 ns、WHS +0.263 ns、0 failing endpoints；66 输入与39输出未设I/O delay，clock-source/skew没有系统级约束。未布局布线，不据此宣称器件可达频率或上板性能。日志和报告位于 `build/keccak_axi_ooc.log`、`build/keccak_axi_ooc/utilization.rpt` 和 `build/keccak_axi_ooc/timing.rpt`。
- 本机 host C Keccak/ML-KEM-512 基线已经通过独立入口测量，数值只描述当前 PC 进程和当前 GCC 构建，不与 RTL 仿真周期或 FPGA 板端性能换算/比较；没有加速倍率结论。板端吞吐/频率、实际 MMIO 访问和硬件 fallback 仍未测。

## 独立 PS 对象与 host C 基线

- `python prj/build_keccak_arm_objects.py` 使用现有 G6 BSP 的 `xparameters.h`（只读）和 Vivado 2026.1 ARM GCC，分别生成实验驱动/adapter 的 Cortex-A9 ELF32 EABI5 hard-float 对象；`readelf -h -A` 确认 ARMv7/VFPv3/VFP registers，驱动反汇编含 `dmb sy`。输出与摘要在忽略目录 `build/keccak_ps_abi/`。这是对象级 ABI/指令验证，不链接、不改 BSP/固件，也不表示现有 G6 XSA 已加入该 IP。
- `python prj/keccak_host_benchmark.py` 用 MSYS2 GCC `-std=c11 -O3 -DNDEBUG -Wall -Wextra -Werror` 编译未修改的 vendored `mlkem_native.c`（ML-KEM-512、portable C backend）。复用 `data/kat/nist_mlkem512.json` 的首条 decapsulation KAT，并用 `sim/tb/test_keccak.py::keccak_f1600` 生成 Keccak 状态期望值；两项正确性检查均通过。当前 Windows 11 x64 主机的 QPC 频率为 10 MHz：9 个样本的 Keccak 中位数/p95 为 215.8/219.7 ns，ML-KEM-512 decapsulation 为 16.325/17.265 µs；每样本分别批量执行 10,000 次置换和 20 次 decapsulation。报告保留原始计时 tick、时钟频率、CPU/compiler 版本与参数以及源码/KAT SHA-256。计时依赖当前主机与调度状态，不能代表 A9 或 FPGA 性能。
- `CTRL_CLEAR` 清除 permutation state 与输入/输出寄存器，但有 RVALID 且遭 backpressure 的 AXI read response 必须维持原 RDATA 直到握手，clear 不可撤回已返回的数据。因此系统级清零结论要求先排空 AXI 事务再 clear；reset 可以取消通道响应。当前 PS 驱动是同步 MMIO，未保留 pending response。

### 完整 ML-KEM 调用链接入验证

- `python prj/mlkem_full_backend_mock.py` 通过 vendored 提供的 FIPS202 custom-header 接口，在 `MLK_CONFIG_SERIAL_FIPS202_ONLY` 实验配置下编译真实 ML-KEM-512 `Decaps`。vendored `mlkem_native.c`、`fips202.c`、`keccakf1600.c` 均保持原样；实验配置头让真实 SHA3/SHAKE 调用解析到 PS driver/adaptor dispatch wrapper，参考 Keccak 以独立 namespace 提供 software fallback。
- 已有 ACVP `nist_mlkem512.json` `tcId=76` 在三条完整 decapsulation 路径上均通过，输出 shared secret 与 KAT 相同：默认关闭时 32/32 次 fallback、MMIO 读写 0；硬件回调 mock 时 32/32 次 mock hardware callback、0 次 fallback；mock timeout 时每个 dispatch 轮询 7 次并 clear，32/32 次 fallback。程序断言 dispatch/callback/launch/clear 数量及返回 secret。
- mock 的置换输出由未修改的 vendored C Keccak 计算。此项是完整算法的 host-side adapter/fallback 集成测试，不是 RTL 或板端硬件验证，不据此宣称加速。复现产物与结构化结果在 `build/mlkem_full_backend_mock/`。

最终源文件 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `src/rtl/crypto/keccak_round.sv` | `134785D2168C19877CFDCE35530BA76B2F437A06559CC78DE6D001F45F8474E9` |
| `src/rtl/crypto/keccak_f1600.sv` | `8BF2073C069963123C1CE3ADECF47E16C15E3A33F941762A45B4A31C979506DA` |
| `src/rtl/crypto/keccak_sponge.sv` | `B77BAA6E1074D6033825986948453F284352DA76D5E19025819927D375B60749` |
| `sim/tb/test_keccak.py` | `26FD358A84795B233041334599FE08368908F439EF5A16B7FB68EAD76BE66DBF` |
| `prj/keccak_ooc.tcl` | `B7C42946818BCA24F303BB24B3305DA014D333095284229ED73FD782C3337D7F` |
| `prj/keccak_benchmark.py` | `0CCE309290A727587DE04B6A00AF3F88BE1F4A53B31FACAFA5154663BA17E1EE` |

## 下一步边界

AXI-Lite state 读写路径、寄存器文档、PS C driver 和 ML-KEM callback adapter 已在独立实验文件中准备好；25 个 64-bit lane 共 200 字节的映射固定为 50 个 little-endian 32-bit MMIO word。要让 PS 实际调用，后续需在单独 variant 的 XSA 中加入该 IP 并分配地址，再显式启用 C adapter。现有视频 PL 顶层和固件没有改动，也没有触板。

板上验收前应在正确 XSA/地址映射下测试 MMIO、reset/timeout/zeroize 与软件回退，测量 MMIO 搬运、启动/等待及硬件置换，再与 vendored C Keccak 的同机/板端基线分开比较；单个置换 24 轮不保证 ML-KEM 端到端更快。

AXI wrapper 最终 OOC 与驱动接口文件 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `src/rtl/crypto/keccak_axi_lite.sv` | `00A1F7A1FF1142F130973D3FBE61BC1E3C0A4B5E229430C7E90407CB89CD2155` |
| `src/rtl/crypto/keccak_f1600.sv` | `8BF2073C069963123C1CE3ADECF47E16C15E3A33F941762A45B4A31C979506DA` |
| `src/rtl/crypto/keccak_round.sv` | `134785D2168C19877CFDCE35530BA76B2F437A06559CC78DE6D001F45F8474E9` |
| `sim/tb/tb_keccak_axi_lite.sv` | `3567D1261CB36394843B81C1518EBCEA3327A075CB9C6FF31EF3B06FD694DD1F` |
| `sim/tb/test_keccak_axi.py` | `2418534685CB3DEB3DAE1675B5247ACA6CA92179457B4E4C860F871CFF5214B8` |
| `sim/tb/test_keccak_driver.c` | `7085211A3B993DC3AAE8AF73591C825DCB46A3BC6D2ECDB71699BCB2FE9DA5FD` |
| `prj/keccak_axi_ooc.tcl` | `DD9BABE3927CB432098916C859B14CA28920738497BA5163B245701F3279D228` |
| `prj/keccak_axi_benchmark.py` | `32937CF3AC5FE2955E4AD7431A5DD330BADEC5503663F1892E4591A7670F17B4` |
| `src/ps/experimental/keccak_accel.h` | `4CA4D3F627E9DB6A0AB0C88AEC5F517C5DA34CD9C77E21615770E29A15FAC7D5` |
| `src/ps/experimental/keccak_accel.c` | `AFB9063C248885B489D6C2B786051AA00F5D57CDD28C7D4AF9AA5E2EC02EE06F` |
| `src/ps/experimental/mlkem_keccak_adapter.h` | `972111DEC10051D79127CCE9837E384B2EA4B7656844E10BA5F0776472C43AB5` |
| `src/ps/experimental/mlkem_keccak_adapter.c` | `9032DDF1506A30E84CE25AD2C6EA9849F36B391BA7C937F089B9012A13D67357` |

本次新增/涉及的离线验证入口最终 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `sim/tb/keccak_host_benchmark.c` | `9AA8A44A4210A2B2F57EC740F3DA41E63067043AE011B8D380439483D77ED45A` |
| `prj/keccak_host_benchmark.py` | `4A768C04DE75F624FA296F5CD9D8974653C21CA9705300A1438F9D1778D4566F` |
| `prj/build_keccak_arm_objects.py` | `D329F17BA33F5F6DBC4A7DB780DD4416355A83AF7764EA8CD19DC60E323DB74D` |
| `src/ps/experimental/keccak_accel.c` | `AFB9063C248885B489D6C2B786051AA00F5D57CDD28C7D4AF9AA5E2EC02EE06F` |
| `src/ps/experimental/mlkem_keccak_adapter.c` | `9032DDF1506A30E84CE25AD2C6EA9849F36B391BA7C937F089B9012A13D67357` |
| `src/ps/experimental/mlkem_fips202_custom.h` | `7C58228F72DB2B7A8DD07662E7288C21051069E332FF54C30B649329D395BC54` |
| `src/ps/experimental/mlkem_fips202_backend.h` | `04D44EC715379A71E695D638B4CB171F5148842565C1BA8B9A250F45C8173A5E` |
| `src/ps/experimental/mlkem_fips202_backend.c` | `2448BA5751C14E3EB4FCF971DE2B9AC2E31F9271BCE10EB208314380A3F9D7F7` |
| `src/ps/experimental/mlkem_full_backend_config.h` | `498F06356BB3969838E98A8EAC0298A27EE5C2E4063EEFAC2B218F0915C02659` |
| `src/ps/experimental/mlkem_full_backend_ref_config.h` | `9AF27A78D9A87A1CF8BCA4F2D0CC76EF84151FBD1943F77B675A8D6A7E64F2CE` |
| `sim/tb/test_mlkem_full_backend.c` | `231252E77EE453C5BBED8DF1D5B57B95A7E65C79AF8F11F50EF23EB28779A0AF` |
| `prj/mlkem_full_backend_mock.py` | `CEF4C4C361925A68B0EDBBDF0F4DFB1EB54D44FD3CBCE98434B313629CD1F74A` |
