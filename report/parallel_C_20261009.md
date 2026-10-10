# C 线：Keccak PS+PL 独立离线实验交付

2026-10-10 更新：根据用户新授权，独立加速器已提前完成实板测试，见 [新 Benchmark](keccak_board_benchmark_20261010.md)。实验固件修复后另建 `build/parallel_20261010/C/firmware_delivery_safe_elfs`；原 20261009 ELF/manifest 保留历史身份，其 project_source hash 因修复已不匹配当前源码，不再作为当前上板预检依据。三轮功能与 fallback 通过，但完整 ML-KEM 硬件路径约慢 8.6%，未集成正式视频。下文是原离线交付快照，原“待测/等待 G0/G7”描述是当时安排。

## 交付结论

已在 `build/parallel_20261009/C/` 生成与现有视频工程隔离的 Zynq-7020 PS+PL 工程、完整 route4k 实现、匹配 XSA/bitstream，以及两种 ARM bare-metal benchmark 固件。Vivado 2026.1 实现与时序/DRC 检查通过；classic HSI 为新 XSA 生成 BSP，ARM GCC 编译通过。所有结果均为本机离线构建或仿真/mock 证据；本轮未访问 UART、USB、JTAG，未下载固件，也没有板端性能数据。

新地址仅对本实验 XSA 有效：Keccak AXI-Lite `0x43C10000`，范围 `4 KiB`，末地址 `0x43C10FFF`，与 RTL 12-bit AW/AR 一致。它不适用于现有视频工程或其他 XSA。PS7 用户参数直接复用已确认的 `prj/build_m01.tcl`，SHA-256 为 `2d0ccb2e57a8fb978ee515240d177eebe0d5bde8d1294436de268f75a7c1d17c`；DDR 配置沿用该源，未推断引脚或外部 DDR 接线。PL 没有外部引脚，仅导出 PS DDR/FIXED_IO。

## 主要产物与证据

- Vivado 系统源：`prj/keccak_system.tcl`、`prj/keccak_system_build.py`。最终系统目录：`build/parallel_20261009/C/route4k/`。
- Vivado 工程、XSA 与报告：`build/parallel_20261009/C/route4k/vivado/`；实现清单：`build/parallel_20261009/C/route4k/build_manifest.json`。
- XSA：`route4k/vivado/keccak_experiment.xsa`，SHA-256 `70fe149c62b3a2cc402adfb78fac625520151309015d89815576784a1fd250a2`。匹配 bitstream SHA-256 `261b8f7dde47ed153f798bc2fc9eecf78570bfc23dde77596c75d644152f407a`。
- `vivado/timing.txt`：全布线状态，10 ns 时钟下 WNS `+0.306 ns`、TNS `0`、0 failing endpoints；WHS `+0.074 ns`、THS `0`、0 failing endpoints。
- `vivado/drc.txt`：Fully Routed，0 DRC checks found。实现日志记载 0 Warning、0 Critical Warning、0 Error；Bitgen 成功。利用率为 6,731 Slice LUT、7,104 Slice Registers、0 BRAM、0 DSP。此为 Vivado 实现报告，不等同于板端时序/功耗验收。
- 固件源和构建器：`src/ps/experimental/keccak_bench_firmware.c`、`prj/keccak_firmware_classic_build.py`，以及 manifest 所列实验驱动、adapter、namespace wrappers。交付目录为 `build/parallel_20261009/C/firmware_delivery/`，其 `build_manifest.json` 记录新 XSA 哈希、从该 XSA 新生成的 BSP 输入哈希、vendored ML-KEM 输入哈希、实验源输入哈希、生成 KAT/config 哈希、ELF/map/readelf/disassembly/编译命令哈希及匹配 bit 与 `ps7_init.tcl` 哈希。
- `firmware_sw` 编译时完全关闭硬件路径，不探测 MMIO，可用于同板软件基线。`firmware_hw` 只有显式硬件构建配置才启用；接触寄存器前要求 Keccak ID=`KCH1`、version=`0x00010000` 匹配。它只能与以上 route4k XSA 配对。
- 固件覆盖软件 Keccak permutation 基线、ML-KEM-512 decapsulation KAT `tcId=76`、MMIO 50 word 写入及 50 word 读回搬运时间、一次硬件 permutation、整次硬件 decapsulation，以及 watchdog timeout 后的软件 fallback 和设备清零检查。计时值应在目标板输出原始 XTime ticks 与频率后再解释；当前没有这些数值，也不预设硬件有收益。

## 离线验证记录

- `.venv/Scripts/python.exe prj/keccak_axi_benchmark.py`：4/4 通过；含 84 个 SHA3/SHAKE 参考向量、AXI 仿真及 host C driver mock。AXI 仿真 start-to-done 为 39 个仿真时钟，不是 A9 或板端时间。
- `.venv/Scripts/python.exe prj/mlkem_full_backend_mock.py`：真实 vendored ML-KEM-512 `Decaps` 的 tcId 76 在 disabled/software fallback、mock hardware、mock timeout 三条 host mock 路径均通过；MMIO 与回退计数断言通过。这不是 RTL/硬件执行证据。
- classic HSI BSP 由 `keccak_experiment.xsa` 生成，日志在 `firmware_delivery/bsp_generate.log`、`bsp_archive.log`；两个 Cortex-A9 ELF 编译、链接、启动映射检查和反汇编检查通过。ELF 编译通过不证明 PS 已从该 XSA 启动。
- `.venv/Scripts/python.exe -m py_compile prj/keccak_system_build.py prj/keccak_firmware_classic_build.py`：通过。

## 复现

Vivado 工程路径较深，Windows 构建使用临时 `P:` 映射到真实的 `build/parallel_20261009/C/` 目录。映射只是构建时路径别名；manifest 和本报告以仓库相对真实目录定位产物。以下命令用于在全新子目录重建，需确认 `P:` 未被占用，并在构建后移除自己创建的映射：

```powershell
subst P: "<repo>\build\parallel_20261009\C"
.venv\Scripts\python.exe prj\keccak_system_build.py --out P:\rerun_route4k --storage-relative build/parallel_20261009/C/rerun_route4k
.venv\Scripts\python.exe prj\keccak_firmware_classic_build.py --xsa P:\rerun_route4k\vivado\keccak_experiment.xsa --out P:\rerun_firmware --storage-relative build/parallel_20261009/C/rerun_firmware
.venv\Scripts\python.exe prj\keccak_axi_benchmark.py
.venv\Scripts\python.exe prj\mlkem_full_backend_mock.py
subst P: /d
```

构建器默认 Vivado 路径为 `E:\fpg\2026.1\Vivado\bin\vivado.bat`，classic BSP/编译器工具根为 `E:\fpg\2026.1`，ARM GCC 位于该工具树。软件构建的输出目录必须是新目录。输入清单与文件哈希以新生成 manifest 为准。

## 下一阶段与未验证项

必须等待 G0/G7 门禁完成并由 A 释放板卡后，才进行任何上板动作。上板时先只用 `firmware_sw` 建立软件计时与 KAT 基线；确认实际加载的是匹配 route4k XSA/bit 后，再运行 `firmware_hw`。核对 ID/version 后记录 permutation 软件/硬件时间、50-word MMIO 搬运、完整 ML-KEM-512 decapsulation、timeout/clear/fallback 的原始输出和频率。报告端到端收益时须纳入搬运与调度开销；MMIO 单项和置换局部收益不能换算成 ML-KEM 收益。如果端到端时间变差，应如实保留负收益。

目前仍未验证：目标板能否以此 XSA 正常启动；该板上的时钟/DDR 实际行为；PS 对 Keccak 的真实 MMIO 访问、ID/version、硬件结果与 timeout/reset；软件和硬件时间；端到端加速比。独立 XSA 也没有板级 PL 引脚或视频/USB 顶层，不能替换正式工程。初版 64 KiB 映射已被 route4k 取代；首次 route4k 的 Windows 长路径失败日志保留在对应 `final4k` 目录，不影响最终实现结果。
