# Keccak/SHA3/SHAKE 独立原型

本原型提供可综合的 Keccak-f[1600] 迭代核心和字节流 sponge：模式 0/1 分别为 SHA3-256/512，模式 2/3 为 SHAKE128/256。核心每周期执行一轮，共 24 轮；SHA3 使用 0x06 域分隔符，SHAKE 使用 0x1f。速率分别为 136、72、168、136 字节。输入以 `in_valid/in_ready` 握手，最后一个字节同时置 `in_last`；空消息用 `in_valid=0,in_last=1` 结束。输出以 `out_valid/out_ready` 握手，SHAKE 在 `start` 时以字节给出长度；SHA3 长度固定为 32 或 64 字节。`clear` 同步取消操作并清零内部/可见状态，`done` 为完成脉冲，`busy` 在完整吸收和挤出期间有效。

状态布局为 `A[x+5*y]`，每 lane 64 位，lane 0 位于低 64 位。核心可单独接收/返回 1600 位 state，便于后续 ML-KEM 置换接口。

## 隔离 AXI-Lite/PS 变体

`board/src/rtl/crypto/keccak_axi_lite.sv` 是独立的 32-bit AXI4-Lite 单 outstanding 包装层，不连接当前视频顶层。地址如下：

| 地址 | 用途 |
|---|---|
| `0x000` | CTRL：写 `1` 开始，写 `2` 清零/中止 |
| `0x004` | STATUS：bit0 busy、bit1 done、bit2 error、bit3 timeout |
| `0x008` | 硬件 watchdog 周期数；0 禁用，复位默认 1024 个 AXI 时钟 |
| `0x00c` | 设备 ID `KCH1` (`0x4b434831`) |
| `0x010` | 版本 `0x00010000` |
| `0x100–0x1c4` | 50 个 state 输入 word，写入；`0x1c8` 为界外 |
| `0x200–0x2c4` | 50 个 result 输出 word，done 后只读 |

25 个 64-bit lane 共 200 字节，对应 50 个 32-bit word。word `2*n` 是 lane `n` 的低 32 位，word `2*n+1` 是高 32 位，字节序为 little-endian。AXI AW 与 W 可分开到达。busy 时不能读 result、读输入或写 state，也不能重启；这些请求返回 SLVERR 并置 error。reset、CTRL clear 和硬件 watchdog 超时都清除内部 state 与输入/输出寄存器；每次 start 先清理上一次内部 permutation state，并清除旧输出。

`board/src/ps/experimental/keccak_accel.c` 默认关闭：`keccak_accel_io.activation_cookie` 为零时完全不调用 MMIO callbacks，ML-KEM adapter直接走所提供的软件实现。只有集成方使用匹配该实验 RTL 的 XSA、确认已分配的地址映射并显式设置 `KECCAK_ACCEL_EXPERIMENTAL_ENABLE` 后，驱动才会读 ID/version；这两个寄存器是已启用映射后的次级核验，不能用于探测一个可能未映射的地址。ID/version失败后不会再写设备。驱动的 `poll_limit` 是 PS 侧有界轮询次数；硬件 watchdog 是 AXI 时钟周期数。没有把任一参数换算成板上毫秒。`mlkem_keccak_adapter.c` 接收 ML-KEM native permutation 函数指针：硬件成功则返回硬件路径，配置未启用、ID/version错误、硬件错误或超时后由调用者提供的软件 Keccak 参考函数回退。未修改 vendored ML-KEM 源码或视频固件。

CTRL_CLEAR 同步清除内部 permutation state 与输入/输出寄存器，但 AXI 协议要求已经置位且尚未握手的 RVALID/RDATA 在 backpressure 期间保持稳定。因此 clear 不能撤回此前已经返回、但尚未被 master 接收的结果数据；若要求形成系统级清零结论，调用方必须先排空/完成所有 AXI 读写事务，再执行 clear。reset 可取消 AXI 通道响应。当前 PS 驱动使用同步 MMIO 访问，没有保留未完成的 AXI read response 场景；此限制仍适用于后续集成系统。

## PS 对象与主机基线

```powershell
.venv\Scripts\python.exe board\prj\build_keccak_arm_objects.py
.venv\Scripts\python.exe board\prj\keccak_host_benchmark.py
```

第一条只读现有 G6 BSP 头文件，用 ARM GCC 生成隔离 Cortex-A9 EABI hard-float `.o`，并记录 `readelf` ABI 属性及驱动 `dmb sy` 反汇编；不链接或修改 BSP。第二条用本机 GCC 编译未修改的 vendored ML-KEM-512 C 聚合源码，以仓库 ACVP decapsulation KAT 和 `sim/tb/test_keccak.py::keccak_f1600` 参考状态验证，再计时 Keccak-f[1600] 与 decapsulation。原始 tick、计时频率、warmup、样本、编译参数和哈希写到 `build/keccak_host_benchmark/result.json`。这些是主机进程时间，不可据此推断 A9/FPGA 性能或加速倍率。

### 完整 ML-KEM 调用链实验

`python board/prj/mlkem_full_backend_mock.py` 使用 vendored 支持的 `MLK_CONFIG_FIPS202_CUSTOM_HEADER` 和 `MLK_CONFIG_SERIAL_FIPS202_ONLY`，不改 vendored 文件。ML-KEM 调用原 `fips202.c` SHA3/SHAKE 实现；它链接到实验命名空间中的 `eye_mlkem_keccakf1600_permute`，后者实际调用 PS adapter。软件参考 Keccak 源以独立 namespace 编译供 fallback 使用。实验跑完整 ML-KEM-512 `Decaps`，ACVP `tcId=76` 在三条路径都匹配同一 shared secret：默认关闭并零 MMIO 访问（32 次软件 fallback）、启用 MMIO mock（32 次硬件 callback，无 fallback）、mock 永不完成触发有界超时（每次轮询 7 次后 clear，再 32 次软件 fallback）。

该 MMIO mock 用未修改的 vendored C Keccak 计算置换结果，只验证软件调度/寄存器交互与完整算法 KAT，不代表 RTL 仿真或板端硬件运行，也不能作为加速证据。正式接入仍需在独立 XSA 中加入 RTL IP、做 RTL/PS 联调，再过 G0/G7 门禁。

## 本机验证

在仓库根目录执行：

```powershell
.venv\Scripts\python.exe board\prj\keccak_benchmark.py
.venv\Scripts\python.exe board\prj\keccak_benchmark.py --synth
.venv\Scripts\python.exe board\prj\keccak_axi_benchmark.py
.venv\Scripts\python.exe board\prj\keccak_axi_benchmark.py --synth
```

仿真入口使用 Vivado 自带 XSim，并由 Python `hashlib` 生成 SHA3/SHAKE 黄金输出；`EYEPQC_SIMULATOR=xsim` 可直接调用测试。若显式选择 Icarus，可运行 `python -m unittest sim.tb.test_keccak -v`；当前记录的 MSYS2 Icarus 13.0 在本机编译期 access violation，脚本会退回 XSim。sponge OOC 综合入口 `board/prj/keccak_ooc.tcl` 和 AXI wrapper 入口 `board/prj/keccak_axi_ooc.tcl` 目标均为 `xc7z020clg400-2`，产物分别写入忽略目录 `build/keccak_ooc/` 和 `build/keccak_axi_ooc/`。

AXI testbench 检查参考状态相等、独立 AW/W 到达、B/R 反压、非对齐/未映射地址、非法控制 WSTRB、busy 写/重启/result读、reset/clear 中止与清零、硬件 watchdog 超时。C mock 检查 50-word MMIO 传输、ID/version 错误时零写入、有界软件轮询超时后清设备以及软件回退。这些是仿真/mock 结果；该变体未连接板卡。

依据：[NIST FIPS 202](https://csrc.nist.gov/pubs/fips/202/final) 定义 SHA3、SHAKE 与 Keccak-f[1600] sponge；本实现仅覆盖上述四种模式。
