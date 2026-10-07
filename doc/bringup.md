# 当前软件版本与首次实机复验

更新：2026-10-07。首次 G3 复验在固件就绪阶段超时；修正 ARM 启动链接配置后等待实机复测。
2026-10-06 离线构建没有连接板卡；2026-10-07 读取了已有 JTAG 调试状态，未打开串口、
重新下载程序或写入启动介质。

## 软件入口

所有命令从仓库根目录执行。Python 3.12 环境使用 `.venv`，依赖固定在
`requirements.txt`；本机 AMD 工具根目录为 `E:/fpg/2026.1`。
其他机器先设置 `EYEPQC_TOOL_ROOT`，并安装 Zynq-7000 器件支持、原生 GCC 和 Icarus。

```powershell
# 默认入口只运行电脑检查，不访问板卡。
& ./run_demo.ps1
# 检查当前程序、启动镜像、源文件和 BSP 哈希，不访问板卡。
& ./run_demo.ps1 -Mode Preflight
# 准备本地开发测试密钥和 ML-KEM DLL，不访问板卡，不覆盖已有密钥。
& ./run_demo.ps1 -Mode Prepare
```

`Check` 的详细日志与结果 JSON 位于 `build/software_checks/<运行时间>/`。
默认顺序在第一个失败项停止；不会把工具缺失或原生 XPM 检查失败当作跳过。
没有 pip 的 uv 虚拟环境也可运行依赖检查。

## 当前交付目录

当前入口默认使用 `build/vitis/usbfix3_20261007/`，使用同一份
`build/vivado/g3_gui/m01.xsa` 构建，包含：

| 路径 | 用途 |
|---|---|
| `g3_camera/build/g3_camera.elf` | 首次摄像头→DDR→PL GCM→DDR 复验 |
| `g4_usb/build/g4_usb.elf` | USB 明文视频基线 |
| `g5_usb/build/g5_usb.elf` | 固定公开测试密钥的 USB AES-GCM 视频 |
| `g6_usb/build/g6_usb.elf` | 开发态 ML-KEM 握手、认证视频和换钥 |
| `<应用>/_ide/bitstream/m01.bit` | 从输入 XSA 提取的同源 PL 配置 |
| `<应用>/_ide/psinit/ps7_init.tcl` | 从输入 XSA 提取的 PS 初始化 |
| `fsbl/build/fsbl.elf` | 同 XSA 生成的 Zynq 首级启动程序 |
| `<应用>/boot/BOOT.BIN` | FSBL、bitstream、应用组成的启动镜像 |
| `<应用>_manifest.json` | 每个应用的源文件、二进制哈希与 DDR 符号 |
| `software_build.json` | 构建方式、710 项生成输入与脚本哈希 |
| `software_verification.json` | 最近一次软件预检结果 |

该目录被 Git 忽略，不能只推送源码就认为二进制已交付。早期 `g3_delivery` 保留为历史产物；
其源码哈希已因修正而失效；`software_ready` 也因缺失 AMD 启动链接配置而停用。
本轮使用 `usbfix3_20261007`，`software_ready_20261007` 及更早目录保留作诊断证据。

重新构建时必须选择未存在的输出目录：

```powershell
& ./run_demo.ps1 -Mode Build -Workspace build/vitis/sw_rebuild `
    -Xsa build/vivado/g3_gui/m01.xsa -ToolRoot E:/fpg/2026.1
& ./run_demo.ps1 -Mode Preflight -Workspace build/vitis/sw_rebuild
```

此路径使用 Vivado 中可用的 HSI 生成经典 BSP，再由 Vitis ARM GCC 编译；
不依赖已禁用的 XSCT 项目流程，也不要求 Vitis IDE 平台生成成功。
Windows 下请使用较短的仓库/输出路径；较长的嵌套路径可能使 HSI 的 FSBL 生成超过路径长度限制。
应用按 `-O3 -Wall -Wextra -Werror` 编译，G6 使用 32 KiB 栈；供应商 BSP/FSBL 保留独立日志。
FSBL 的 `ps7_init.c/.h` 与 XSA 逐字节一致，Bootgen 已生成并读取各启动镜像的分区表。
这仅证明软件产物可构建和解析，尚未证明板卡可以从 SD 启动。

## 首次实机：先验证 G3

确认板卡为与工程匹配的 Zynq-7020，目标 `xc7z020clg400-2`。
底板和核心板修订、两颗 DDR 型号/供电见 [板卡说明](../board/README.md)。
摄像头为 OV5640/ATK-MC5640 V1.2，接 P2；接线方向和供电以对应修订原理图为准。
JTAG USB 连接电脑，板卡使用对应 DC 电源；UART 接 PS 串口通道。
历史 V3.9 底板记录 P5 的 1–3、2–4 对应 PS 串口，不能未经核对就套用到其他底板修订。
拨码和跳帽由用户按实物板卡资料确认，本文件不猜测位置。

在一个 PowerShell 窗口启动硬件服务：

```powershell
& 'E:/fpg/2026.1/Vivado/bin/hw_server.bat'
```

在另一个窗口从仓库根目录执行，先在硬件管理器核对 JTAG 器件：

```powershell
& ./run_demo.ps1 -Mode G3
```

若仅枚举到 `DAP (AHB AP transaction error)` 和 `xc7z020`，但没有 APU/Cortex-A9，
则失败发生在下载前，不应重复执行 G3。先退出硬件管理器/其他调试会话，
停止原 hw_server；板卡完整断电，并按对应板卡资料核对 JTAG 启动模式后重新上电，
再启动单个 hw_server。启动模式在 POR 时采样，普通复位不等同于完整重新上电，见
[AMD UG585](https://docs.amd.com/r/en-US/ug585-zynq-7000-SoC-TRM/Introduction)。
本指南不推测底板拨码的具体位置，也不改写 SD/QSPI。

先运行只枚举目标的检查（不复位、不访问板端寄存器/内存、不下载）：

```powershell
& ./run_demo.ps1 -Mode JtagCheck
```

出现 `JTAG_CHECK_OK APU Cortex-A9#0 xc7z020` 后再运行 G3。
检查日志保存在 `build/jtag_checks/`；若错误持续，保存输出并核对电源、复位、启动模式和接线。

该命令先预检，再临时加载 bitstream/ELF 并采集一帧，不写 SD/QSPI/Flash。
`G3_LOAD_OK` 只表示下载/启动命令已完成，`G3_READY_OK` 才表示固件邮箱就绪。
若就绪超时，日志会保留 CPU PC/CPSR/LR/SP 和邮箱前 64 字节；该输出不包含开发密钥。
预期出现 `G3_BOARD_OK`，结果保存在 `data/captures/g3_*/`，包含 JPEG、密文、日志与
`result.json`。必须同时核对图像可解码、逐包认证/逐字节一致以及错误/丢帧/溢出计数。
G3 的时序满足当前用户约束，但 PCLK 非专用时钟路由 `PLCK-12` 警告仍需实机评估。

## G3 通过之后：G6

增加 USB Slave 数据线；Windows 应枚举实验 CDC 设备，测试 VID/PID 为 `03FD:7020`，
串口号由系统动态分配，代码自动识别唯一设备。关闭其他占用该端口的串口工具。

```powershell
& ./run_demo.ps1 -Mode G6 -Seconds 10 -Show
```

预期出现 `G6_USB_OK`，完成坏 Finished 拒绝、两段认证视频及主动换钥；保存结果 JSON 和
首/末帧。本入口暂时仍使用本地开发密钥/Windows 随机种子经 JTAG 注入，不是独立设备密钥管理。
对应文件在 Git 忽略的 `board/output/m09/` 中，不能放入公开提交包。
G6 `BOOT.BIN` 也仍等待该开发态注入，生成启动镜像不代表消除了 JTAG 密钥依赖。

若预检报源码或二进制改变，应从同 XSA 重建到新目录；若硬件下载、UART、摄像头或 USB
出现异常，保留日志，在第一处失败停止。本轮不继续 SD 启动、20 次冷启动、物理故障或 2 h 长测；
这些是下一步用户实机验证的范围。

## G7 恢复软件及单次用户验证

恢复逻辑、故障计数和合成 USB 故障覆盖见 [G7 软件恢复记录](../report/g7_software_recovery.md)。
使用仓库根目录的 `run_demo.ps1 -Mode G7`。它复用有匹配构建及出图记录的固件，或临时下载并完成开发态预配，
再等待 `03FD:7020` CDC；等待枚举本身不表示数据线未连接。取得至少两帧
认证视频并确认后台流标记后，先提示拔出 USB Slave 数据线并保持拔出；检测到移除后才提示插回，
插回由脚本自动检测，无需按 Enter。然后提示按 Enter 模拟接收进程异常退出；每次之后必须完成新
握手及至少两帧视频。超时、没观察到 PnP 移除/重新枚举或新帧不足都会失败/未完成，不会批量重试。
该入口不拔摄像头。实机尚未完成时，不得将软件注入或自动测试写作 G7 物理故障通过。
