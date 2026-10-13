# Board SD 部署与 G0 冷启动记录（2026-10-13）

本报告仅负责板端。用户已报告 Android 可显示视频、约 40 fps 足够；本次没有重新测量手机帧率。
当前 SD 根目录镜像是独立 G0 DDR/定时器/LED 自检，不是 G6 视频应用；G6 自主密钥装载尚未闭环。

## 本轮新构建

旧 `g0_20261008b_startup_final2` 不在本地构建目录，未复用旧报告中的镜像。
执行 `board/prj/build_g0.ps1 -ToolRoot D:/AmdDesignTools/2026.1 -BuildName g0_board_sd_20261013_1`，
从当前目录源码重新生成 XC7Z020CLG400-2 XSA、匹配 BSP/FSBL、bitstream 和 G0 ELF/BOOT.BIN。

| 项目 | 本轮产物/证据 |
|---|---|
| XSA | `build/vivado/g0_board_sd_20261013_1/m01.xsa` |
| XSA SHA-256 | `0c5f1024abd509c7b2d59e115620c061ab9b77b9217f2a553e08710cbd217b2b` |
| BOOT.BIN | `build/vitis/g0_board_sd_20261013_1_startup/g0_startup/boot/BOOT.BIN` |
| BOOT SHA-256 | `3053401b6fca21b83092431656d3c0b0842b8d1cbcc77bbb54dc1c8eebd015da` |
| BOOT 字节数/build ID | 4,199,056 / `47f571a09684` |
| 清单 | `build/vitis/g0_board_sd_20261013_1_startup/g0_manifest.json` |
| 实现检查 | `build/g0_meta/g0_board_sd_20261013_1/implemented_io.txt.verified.txt`，H15/LVCMOS33/10 ns |
| 时序 | WNS 6.068 ns、WHS 0.130 ns；心跳 LED 外部输出无 output delay 的提示保留 |

G0 preflight 已通过；匹配 FSBL 的 `ps7_init.c/.h` 由构建工具与 XSA 逐字节比对，
Bootgen 生成并读回分区信息。`board_validated=false` 保留，不以构建替代实测。
DDR 自检只覆盖 64 KiB scratch，不能称全片 DDR 检查。

## 卡识别与文件级部署

用户连接读卡器后重新枚举：Disk 1 为 `DD-TEK READER`、USB、31,266,439,168 字节、MBR，
非系统/非启动磁盘；唯一分区对应 E: FAT32/Removable，卷序列号 `12345678`。
部署前重新校验这些条件，根目录完整列举只有 `System Volume Information`，原 `BOOT.BIN` 不存在。
因此没有被替换文件；未格式化、未擦盘、未改分区，也未覆盖其他根目录文件。

`board/output/sd_deploy_20261013_1/before.json` 保存识别、分区、目录及原 BOOT 缺失记录。
使用 `FileMode.CreateNew` 写 `E:/BOOT.BIN`，`Flush(true)` 后重新读取文件计算 SHA-256，
与本轮镜像逐字节摘要一致。部署结果保存在同目录 `deployment.json`。
如果后续部署时原 BOOT 已存在，必须先另存本机并校验后再替换；本轮“原文件不存在”的记录不能外推到其他卡。

读卡器出现前曾构建原生 xilffs/XSdPs 只读探针，ARM 编译和主机解析自检查通过。
探针未取得卡端有效结果，其 XSDB 客户端已停止；未调用写文件、格式化或删除接口。
读卡器路径已满足任务，因此不增加常驻工具；调查源码/ELF在忽略目录
`board/output/sd_read_probe_live_20261013_1/` 保留，不能宣称板上只读探测成功。

## 具体启动/供电依据

本地官方底板 V3.9 原理图第 2 页 BOOT OPTION 表和用户快速体验 V3.0 第 95 页近照均确认：
**红色二位 `BOOT_CFG` 的 1=OFF、2=OFF 为 SD Card**。它位于 BAT1 纽扣电池旁、PL_RESET 红按键旁；
按实物的 ON 标识判断方向，不能因图片旋转而猜上下。V3.9 正面装配图提供器件位置。

原理图第 6 页中 USB_UART 的 VUSB 单独经 U22 给 CH340 供电；VUSB 与 DC 输入降压后的 VBTN
都在 K1 主电源开关前，主 +5V 在 K1 后。因此只拔 DC 电源而保持 K1 接通，USB 仍可供主电源，不能当冷启动。
采集可保持 USB_UART 连接，关闭 K1 主开关并确认主 PWR/核心灯全灭，拔视频 USB Slave 和 JTAG，
断电插卡、BOOT_CFG 两位均 OFF，再打开 K1。上述为原理图连接证据，未用万用表实测断电电压；
若 K1 关闭后主灯仍亮，必须停止并核对剩余供电路径。

依据文件（本地官方资料，只读）：

- `D:/BaiduNetdiskDownload/正点原子领航者/3_开发板原理图和硬件相关文件/领航者ZYNQ底板原理图_V3.9.pdf`，SHA-256 `ec8b68eeb07e0743e6c60528444f6aeb457dc60e897ddf9eb86d5a56c1ab6a69`。
- `D:/BaiduNetdiskDownload/正点原子领航者/9_领航者ZYNQ底板V3.7版本（音频芯片为WM8960）/1_领航者ZYNQ开发板出厂综合测试/【正点原子】领航者ZYNQ开发板用户快速体验_V3.0.pdf`，第 9/95 页。
- `D:/BaiduNetdiskDownload/正点原子领航者/3_开发板原理图和硬件相关文件/硬件相关文件/领航者结构图&DXF&封装库/领航者底板/领航者ZYNQ底板结构图/领航者ZYNQ底板结构&装配图正面_V3.9.pdf`。

关键页已渲染核对，临时图在 `tmp/pdfs/sd-base-2.png`、`sd-base-6.png`、`sd-manual-95.png`、`sd-assembly-1.png`。

## UART/验收状态

本轮 Python 串口枚举为 COM4=CH340 调试 UART、COM7=USB 视频，端口号只适用于当前机器。
PC 8765 转发服务由 PC 聊天暂停。板端未自行管理 PC 进程。
2026-10-13 14:02:04（UTC+8）COM4 已被动打开，115200/8N1、DTR/RTS=false。
采集路径 `data/captures/g0/board_sd_cold_20261013_1.jsonl`，2400 秒超时、要求目标 uptime 至少 1800 秒、
UART 断线立即失败。完整验收要求匹配 build ID、BOOT_MODE=0x05、READY、连续 STAT、每分钟 DDR 复测，
且 ddr_err/assert/exception/timer_err=0，并由真实操作者确认 SD 卡、拨码、完全断电动作及 H15 LED 约 1 Hz 闪烁。

首次实际启动：2026-10-13 14:08:37（UTC+8）UART 确认 `Boot mode is SD`、`SD Init Done`、
`DMA Done`、`FPGA Done`，随后 `Handoff Address: 0x00000000` / `No Execution Address JTAG handoff`。
没有 G0 BOOT/READY，故本轮失败，不能算 30 分钟或冷启动通过。collector 已停止，原始 JSONL 保留，
SHA-256 `781c4914f31c7a2f824744903ca706d18f34ad071a7a2fbc9210757210bf138f`；下一轮使用新文件。

根因：ARM GCC 生成的 `.note.gnu.build-id` orphan 被共用 `a9_ddr.ld` 放到地址 0，
ELF 多出 36 字节的 PT_LOAD；Bootgen 将其作为首个应用分区（load=0、exec=0x100000）。
匹配 FSBL 的 `image_mover.c` 对未签名/未加密的零加载地址在复制前退出循环，因此没有设定跳转入口。
不能据此宣称已复制覆盖 OCM 或损坏 FSBL。

协调聊天接管后，仅在共用 DDR linker 丢弃该构建标记段，并新增真实 ARM GCC 回归检查所有 LOAD 位于 DDR、
入口位于可执行 LOAD。所有共用该 linker 的 G0/G6/Keccak builder 都获得修复；已有历史镜像不被修改或重新验收。
新软件目录 `build/vitis/g0_board_sd_20261013_2_startup` 重新生成 BSP/FSBL，复用同轮已实现的 XSA/引脚/时钟证据，
没有重复综合未变的 RTL。应用仅剩一个 LOAD，Bootgen 应用 load/exec 均为 `0x00100000`；G0 preflight 通过。
新 BOOT.BIN 为 4,198,992 字节，SHA-256 `079482ff600bac35203dd75e72080940e8cc2bcd9a3d5d485dd51ffec584ec1c`。
build ID 仍为 `47f571a09684`（由应用 C/XSA 推导），必须结合 BOOT hash 和 source_inputs 区分镜像。
当前：新镜像离线验证通过，等待安全更新 SD 与新的实测；冷启动/30 分钟/物理复位均未通过。
不写 BOOT_MODE 寄存器，不以 JTAG 暖启动作为 SD 证据。

复位采集器原先在第二次 BOOT 后立即停止，漏第二次 READY/STAT，已改为第二次 STAT 后停止。
`board/prj/tests/test_g0_capture.py` 用模拟 UART 复现并验证完整第二次启动证据；该 1 项测试和原 7 项日志解析测试通过。

## G6 独立视频限制

现有 `g6_mobile_bridge_20261012_1` 的固件清单 73 项哈希核对通过，
但 `verify_software.py` 全构建追溯检查失败：`software_build.json` 引用缺失的
`g6_usb/external_sources/src/xusbps_endpoint.c`。没有修改摘要或跳过检查冒充全检通过。

G6 启动仍等待 `g6_ready=PROVISION_MAGIC`，从 JTAG mailbox 读静态 ML-KEM 私钥与 seed。
直接创建 G6 BOOT.BIN 仍不能自主认证视频；可选的开发态 SD 私钥/每次启动新熵装载需要另行设计和授权，
并明确明文 SD 私钥、可信 PC、JTAG 及非生产安全边界。生产 provider、真实熵源/secure boot/eFuse 不由本次 G0 验收完成。

本轮未写真实私钥到提交固件或 SD、未烧 eFuse、未做全 DDR 检查或手机新实测。
