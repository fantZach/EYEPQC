# M02 布局布线与现场准备（2026-10-11）

## 结论

此前默认 Vivado 实现策略在最终布线后 WNS 为 `-0.052 ns`，4 个 setup 端点失败，不能用于板测。保留失败候选后，
以相同 M02 RTL、XDC 和板级探针分别运行 `Explore` 与 `AggressiveExplore`。两次完整构建均通过当前时序门禁，
结果相同：WNS `+0.017 ns`、TNS `0 ns`、WHS `+0.041 ns`、THS `0 ns`、WPWS `+4.146 ns`，
2336 个受约束端点中 setup/hold 失败端点为 0，DRC 检查项为 0。AggressiveExplore 没有增加余量，
后续优先使用更简单的 `Explore` 候选。17 ps setup 余量很小，不能描述为宽裕时序。

## 固定候选身份

Explore 构建目录：`build/vivado/m02_coldboot_candidate_20261011_explore`。

| 产物 | SHA-256 |
|---|---|
| `m01.runs/impl_1/system_wrapper.bit` | `210b3eeb326a5e64961efc2e73730fa9a9548aa18af8fb4d1db346154bad9edd` |
| `m01.xsa` | `36d19203839d4c29a4593192d63d8fd6a5c0060812840044b80d23bd24819b3b` |
| `m01.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl` | `843f5b69dcb988b42d181a3e52c6670b95d9584aba8937afa64d516543e03380` |

Vivado 为 `2026.1`，器件为 `xc7z020clg400-2`。XSA、bit 和 PS7 初始化脚本与 `prj/run_m02_jtag.tcl` 要求的路径一致。
板上下载仍未执行；成功构建只说明离线实现和约束门禁通过。

## 复核与板测准备

- `sim/tb/test_m02.py`：4/4 通过；覆盖 SCCB 引脚模型、OV5640 配置、探针 GPIO 映射，以及包装器对成功/预期故障/假成功的判断。
- KX41 预检：715 项输入 hash；ELF `78b37fc5b8410cc8e868a8a2febc833e0397d0573c5d5c043399f53556a2824d`、XSA `ed634c6d480de36c16af64962093069cc120e04af5b38498978e210bf404318d`；WNS `+0.029 ns`、WHS `+0.082 ns`、 fully-routed，manifest 验证成功。该命令使用 `--verify-only`，没有访问硬件。
- KX41 UART 严格验收器：11 项单元测试通过。三窗口全 60 组实板 KAT 尚未运行。
- 最近的 Windows present-only PnP 查询没有发现 `03FD:7020`、Xilinx/Digilent JTAG 或可用串口；M02 和 KX41 均未上板。

探针新增 `-SensorResets 1`，默认 `20` 次同会话传感器 RESET/PWDN 回归保持不变。后续真实掉电批次必须由操作者每轮完整断电、重新上电并单独保存日志；
一次命令内的 20 次传感器复位和仿真 20 次配置都不计入实物冷启动。该探针会用 JTAG 临时下载 PL 并由 GPIO 发起配置，
所以它验证的是物理掉电后相机重新配置，不是独立 SD/Flash 启动或自动启动链路。

缺摄像头负向门禁使用 `-SensorResets 1 -ExpectCameraFailure`。只有本次控制器返回非零错误码，且 `failed=1`、
`configured=0`、`capture_resetn=0` 时包装器才接受为预期失败；XSDB/Tcl 工具故障不能通过。操作者应先完全断电，再拔除整个模组连接器，
不做带电插拔或故意短接错误引脚；该负向批次与正常冷启动批次分开归档。

复现时请从以下两条命令中选一条，并使用全新的输出目录：

```powershell
& 'E:/fpg/2026.1/Vivado/bin/vivado.bat' -mode batch -source prj/build_m02_timing_explore.tcl `
  -log build/m02_coldboot_explore.log -journal build/m02_coldboot_explore.jou `
  -tclargs build/vivado/m02_coldboot_explore Explore

& 'E:/fpg/2026.1/Vivado/bin/vivado.bat' -mode batch -source prj/build_m02_timing_explore.tcl `
  -log build/m02_coldboot_aggressive.log -journal build/m02_coldboot_aggressive.jou `
  -tclargs build/vivado/m02_coldboot_aggressive AggressiveExplore
```

当前继续门槛是恢复 USB CDC/JTAG 枚举。恢复后优先以 Explore 构建逐轮采集 M02 的断电与缺摄像头证据；KX41 则使用其独立 XSA/ELF，
串行运行 software、KX41 hardware、forced-timeout 三窗口，不与 M02 板测混用或并行占用 XSDB。
