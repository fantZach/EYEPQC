# G0 启动闭环离线准备与验收记录

更新时间：2026-10-08。final2 镜像的临时 JTAG 启动、30 秒 DDR/定时器检查及 H15 LED 观察已通过；SD 独立启动、物理复位和断电冷启动 30 分钟门禁仍未验收。

## 已准备的独立启动镜像

最终开发态 G0 镜像位于 `build/vitis/g0_20261008b_startup_final2/g0_startup/boot/BOOT.BIN`，SHA-256 为 `4c2760e609024f329f3f9d0c4aeb6d84c9de70872ce900e89d9d562a33410386`，build ID 为 `9654837c3428`。匹配的硬件平台是 `build/vivado/g0_20261008b/m01.xsa`，SHA-256 为 `40fe2867110ed4b1bf05889220cccbe35fbd48f652ef6607cf822e1750823a2d`。镜像由同一 XSA 生成 FSBL，Bootgen 已读回 BOOT.BIN 分区；它不初始化网络或 USB，也不需要 G6 开发私钥或会话随机种子。

Vivado 2026.1 对本轮实现后网表的检查报告给出 `led PACKAGE_PIN=H15`、`IOSTANDARD=LVCMOS33`、heartbeat 时钟周期 `10.000 ns`。XSA HWH 同时确认 SD0 已启用、FCLK0 为 100 MHz，外部 LED 连接 heartbeat 模块。2026-10-08 的临时 JTAG 实测中，操作者确认板上红色 LED 稳定闪烁；该观察仅覆盖这次 JTAG 运行，不代表 SD 启动或长期稳定性。

PS 应用只在 DDR BSS 中执行 64 KiB scratch 检查，manifest 的 `full_ddr` 语义为 `no`。本次 ELF 布局显示 scratch `0x0010C0C0–0x0011C0C0`，位于 BSS `0x0010C040–0x0011C280` 内，heap 从 `0x0011C280` 开始，未与 heap/stack 重叠。代码记录 BOOT_MODE、DDR 检查计数、50 ms 定时器 tick、assert/exception 和错误计数；它不覆盖整片 DDR。

构建 manifest 位于 `build/vitis/g0_20261008b_startup_final2/g0_manifest.json`，其中记录 XSA/BOOT/ELF/FSBL、实际实现报告、生成 BSP 的头文件与 `xscutimer_g.c`、`xscugic_g.c`、`xinterrupt_wrap.c` 哈希，以及 `libxil.a` 哈希和编译/链接参数。当前 `board_validated=false`。平台源代码在 Vivado 构建前有单独快照，构建后校验一致；软件迭代复用了同一份生成 BSP，最终清单绑定该 BSP。

## 可复现的离线检查

在仓库根目录使用：

```powershell
.\.venv\Scripts\python.exe -m py_compile prj\g0_acceptance.py prj\build_g0_software.py prj\g0_source_manifest.py sim\tb\test_g0_acceptance.py
.\.venv\Scripts\python.exe -m unittest sim.tb.test_g0_acceptance -v
.\.venv\Scripts\python.exe sim/tb/test_m01.py M01.test_board_reset_polarity
.\.venv\Scripts\python.exe prj/g0_acceptance.py preflight --manifest build/vitis/g0_20261008b_startup_final2/g0_manifest.json
```

G0 日志解析的 7 项测试全部通过，覆盖 30 分钟冷启动计时和 DDR 计数、reset 后计时重新开始且恰好两次有效启动、第二次 READY/STAT、额外启动/故障拒绝、UART 断线重连导致证据失败，以及非 SD BOOT_MODE 的临时 JTAG LED 探测。Vivado 2026.1 XSim 跑原 `sim/tb/tb_heartbeat.sv` 得到 `HEARTBEAT_PASS`；已有 M01 reset 极性测试也通过。

`prj/build_g0.ps1` 是完整的新构建入口，要求全新 `BuildName` 和 `E:/fpg/2026.1` 工具根目录，例如：

```powershell
.\prj\build_g0.ps1 -ToolRoot 'E:/fpg/2026.1' -BuildName 'g0_新的唯一名称'
```

构建只创建 Vivado/Vitis 工作区和 BOOT.BIN，不访问 UART/JTAG、板卡、SD 或 Flash。当前板测使用 `prj/run_g0_jtag.ps1`，默认只做离线预检；只有在协调好的板卡独占窗口才可添加 `-Execute`。

## 现场阶段与边界

用户已说明板上 SD 卡保持原样、手边没有读卡器；本轮不写卡、不调整启动跳帽。2026-10-08 已完成下述短 JTAG 探测，原始串口 JSONL 与验收结果保存在 `data/captures/g0/20261008_jtag_led_probe_205256.jsonl` 和同名 `.result.json`：

1. 在串口终端启动被动采集：

   ```powershell
   .\.venv\Scripts\python.exe prj/g0_acceptance.py capture --manifest build/vitis/g0_20261008b_startup_final2/g0_manifest.json --port COM14 --scenario jtag_led_probe --seconds 120 --minimum-seconds 30 --reconnect-seconds 0 --output data/captures/g0/20261008_jtag_led_probe_205256.jsonl
   ```

   本次 COM14（CH340，VID `1A86`、PID `7523`）已成功采集本镜像的 G0 UART 日志；COM16 属于 G6 USB probe。采集器不会自动枚举选择端口，成功打开 COM14 后才显示“UART 已就绪”。

2. 确认采集器已记录 `uart_connected` 后运行：

   ```powershell
   .\prj\run_g0_jtag.ps1 -Workspace build/vitis/g0_20261008b_startup_final2 -Execute
   ```

   实测捕获 BOOT `boot_mode=0x00`、DDR PASS（uncached+cached，64 KiB scratch，`full_ddr=no`）、TIMER PASS（50 ms/20 Hz）、READY 和 10/20/30 秒 STAT；`ddr_err/assert/exception/timer_err=0`，30 秒 `ticks=600`，人工观察 H15 红色 LED 闪烁为 yes，结果 PASS。用户补充观察到加载前红灯一直闪，临时复位/重配置期间停闪，之后恢复闪烁；这与本次 JTAG 加载过程一致。此探测不要求 BOOT_MODE=SD0，也不作为 SD 启动证明。

3. 本次 JTAG 探测后已恢复 `build/vitis/usbfix3_20261007` G6 baseline，以 `E:/fpg/2026.1` 工具根重新加载，并按流程注入开发态私钥和新随机种子；单会话 3 秒认证回归 PASS，140 帧/2.9314 秒（47.42 fps），984 个认证视频包。结果在 `data/captures/g6_usb_20261008_205623_506211/result.json`。自建 hw_server 已关闭，COM14/COM16 无采集进程占用。

完整 SD 门禁仍需有读卡器或用户批准的镜像写入方案、专用卡、对应板版的 SD 启动跳帽/拨码确认、人工完整断电再上电、LED 观察，以及连续 30 分钟 UART 统计。采集器会检查 BOOT_MODE 为 `0x05`，但寄存器值不能代替人工确认实际跳帽和冷启动动作。标准为 30 分钟无应用重启、DDR 错误、异常或定时器错误；不额外增加 20 次冷启动，后者属于 M02。

本次 30 秒 JTAG 结果只证明对应 G0 镜像在当时完成启动、局部 DDR scratch/计时器检查并观察到 LED；它不覆盖全片 DDR、物理复位、断电冷启动或 SD 独立启动。历史 M01 产物缺失，且历史 `board_validated=false`，不能用旧 BOOT.BIN 或历史 JTAG 日志替代本轮镜像的 SD/冷启动验收。
