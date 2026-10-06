# 领航者 7020 官方例程研究

更新：2026-09-27。结论来自用户提供的原始源码、BD、XDC 和本机 AMD 驱动，
并对照 AMD IP 文档与 Linux 上游 OV5640 驱动。这里记录源码事实与迁移建议，不代表上板通过。

## 1. 来源与复现

研究使用的官方资料目录由项目使用者提供，例程源码位于资料包的 `4_Source_Code` 子目录。
新增硬件资料见第 7 节。
已按需解压 8 个工程，保留原文件，不导入旧 BSP、可执行固件和实现结果。
另有少量生成的 IP 源码/网表用于核对接口；它们不是新工程的构建输入。

| 压缩包 | 字节数 | 提取文件数 | SHA-256 |
|---|---:|---:|---|
| `1_FPGA_Design/ZYNQ_7020_FPGA.rar` | 1519052295 | 30 | `02b4088192c1b38fc7c1d07f589a5dbcf30dc91f2f5b64b912ba62641d637108` |
| `2_Embedded_Vitis/ZYNQ_Vitis_7020.rar` | 2249047175 | 2237 | `017e8960dcb9e514da9c6663bcbeca485690bc20dc4c928b5ccbaf390594a873` |

在空的 `board/vendor/` 中运行（现有文件不会被覆盖，重复导入会报错）：

```powershell
& ./prj/import_vendor.ps1 -SourceRoot 'D:/vendor-materials/4_Source_Code'
```

本次核对 `board/vendor/manifest.json` 中 2267 个条目，全部存在。
解压目录被 Git 忽略；保存此报告和导入脚本即可重现来源。
迁移后的两份压缩包已重新计算 SHA-256，字节数和哈希与上表一致。
官方文件保留原版权头；不能把“提供了源码”当作允许任意再分发的开源许可证。

| 例程 | 用途 | 本项目取舍 |
|---|---|---|
| FPGA `1_led` | PL LED/按键约束 | 取引脚，不把它与 PS MIO LED 混淆 |
| FPGA `42_ov5640_udp_pc` | RGB565，经 PL RGMII/ARP/UDP 发送 | 取摄像头引脚和 SCCB 时序参考；不引入第二套网络栈 |
| Vitis `1_hello_world`、`3_gpio_emio` | PS 基础配置、EMIO | 核对器件、DDR、UART 和 GPIO |
| Vitis `8_uart_intr_loop`、`9_timer_intr_led` | UART/GIC/SCU Timer | 取连接方法；驱动使用本机 BSP 版本 |
| Vitis `40_lwip_echo_server` | PS GEM + Standalone/lwIP | M01 网络基线，实际 TCP 端口是 7 |
| Vitis `44_ov5640_ps_eth_udp_pc` | JPEG 字节经 PL、DMA、DDR、PS GEM | 取 JPEG 初始化与 HP0/DMA 拓扑；不能整套照搬 |

8 份 XPR 均标注 Vivado 2020.2、`xc7z020clg400-2`；6 份 PS BD 也记录 2020.2。
部分 RTL/生成文件的头部日期为 2025，说明压缩包有后续更新。
XPR 中的 `navigator_v2` 原作者路径只是线索，不足以确认实物板卡版本。

## 2. 已核对的板级配置

PS 配置依据 [echo BD](../board/vendor/ZYNQ_Vitis_7020/40_lwip_echo_server/lwip_echo_server.srcs/sources_1/bd/system/system.bd)
与 [camera BD](../board/vendor/ZYNQ_Vitis_7020/44_ov5640_ps_eth_udp_pc/ov5640_ps_eth_udp_pc.srcs/sources_1/bd/system/system.bd)。
echo BD 只显式保存部分参数，省略字段不能当成关闭或零；结合 hello BD 和导出的 Tcl 读取。

| 项目 | 源码配置 |
|---|---|
| 器件 | `xc7z020clg400-2` |
| PS 参考时钟 / CPU | camera BD：33.333333 MHz；CPU 实际频率约 666.666687 MHz |
| DDR | 32-bit，约 533.333374 MHz；应用 DDR 起址 `0x00100000`，高址 `0x3FFFFFFF` |
| UART0 | MIO 14..15，UART 外设时钟 100 MHz，camera BD 默认 115200 baud；基址 `0xE0000000` |
| PS GEM0 | RGMII MIO 16..27，MDIO MIO 52..53；基址 `0xE000B000`，千兆目标时钟 125 MHz |
| PS MIO 电平配置 | Bank0 3.3 V，Bank1 1.8 V；不等于摄像头 PL IO 电平 |
| camera PL 时钟 / 复位 | FCLK0 100 MHz；FCLK_RESET0_N → proc_sys_reset → 外设复位 |
| camera AXI / 中断 | GP0 控制 DMA/GPIO；S2MM 经 HP0 写 DDR；DMA IRQ 接 IRQ_F2P，DIRECT 模式 |
| camera SCCB | EMIO GPIO 宽度 2；PS GPIO 编号 54=SCL、55=SDA |
| LED | PL LED H15、PL 按键 L14；定时器例程使用另一只 PS MIO0 LED |

DDR 有必须解决的差异：hello、GPIO、UART、timer、echo 这 5 个例程使用
`MT41K256M16 RE-125` / `DDR 3 (Low Voltage)`；camera 例程使用
`MT41J256M16 RE-125` / `DDR 3`。
hello 和 camera 显式 DDR 参数比较仅这两项不同，但仍不能推断实物供电和芯片兼容性。
M01 最初以 hello/echo 配置为待确认基线，不用 camera 的 DDR 类型覆盖它；
用户提供海力士丝印与颗数后已改为 Custom 时序，见第 7 节。

摄像头引脚在两个摄像头工程中完全一致，均配置 `LVCMOS33`。
依据 [PS 摄像头 XDC](../board/vendor/ZYNQ_Vitis_7020/44_ov5640_ps_eth_udp_pc/ov5640_ps_eth_udp_pc.srcs/constrs_1/new/system_wrapper.xdc)。

| 信号 | 封装引脚 | 备注 |
|---|---|---|
| PCLK / VSYNC / HREF | W14 / U12 / T12 | PCLK 域采样 |
| D[0..7] | R14, U13, V13, U15, U14, W13, V12, Y14 | 按此顺序，不反转字节位序 |
| RESET_N / PWDN | P14 / V15 | 低有效复位 / 高有效休眠 |
| SCL / SDA | T10 / T11 | camera XDC 用 EMIO[0]/[1]，SDA 开启内部 PULLUP |
| FPGA 外部时钟 / 复位 | U18 / N16 | FPGA42 XDC：50 MHz；camera44 使用 PS FCLK，不需要这组端口 |

两个工程的 PCLK 约束不同：FPGA42 为 40 ns（25 MHz），camera44 为 13.888 ns（约 72 MHz）。
RGB 配置表还出现“PCLK=48MHz”的注释，不能拿注释代替实测。
两份 XDC 都放宽了 `CLOCK_DEDICATED_ROUTE`，没有完整的 DVP 输入延迟约束。
后续需按实物输入时钟/摄像头配置测量 PCLK，再补输入时序和 CDC 检查。
两个顶层都未导出摄像头 XCLK，初始化注释假定输入 24 MHz；模组时钟来源仍需原理图确认。

## 3. JPEG 配置已确认，不能按函数名或单个寄存器判断

[camera 初始化](../board/vendor/ZYNQ_Vitis_7020/44_ov5640_ps_eth_udp_pc/vitis/ov5640_ps_eth_udp_pc/src/ov5640/ov5640_init.c:78)
先读 `0x300A/0x300B`，要求 ID 为 `0x5640`，然后执行软件复位和初始化。
SCCB 地址是 7-bit `0x3C`，线上写/读地址字节为 `0x78/0x79`。

| 寄存器 | camera44 最终值 | 用途/判断 |
|---|---|---|
| `0x4300` / `0x501F` | `0x30` / `0x00` | YUV422/YUYV，作为 JPEG 压缩输入格式，并不排除 JPEG 输出 |
| `0x3821` | `0x20` | bit5 置位，JPEG enable；官方代码“左右翻转”注释不完整 |
| `0x3002` / `0x3006` | `0x00` / `0xFF` | JPEG FIFO/模块解除复位，相关时钟开启 |
| `0x4713` / `0x4407` | `0x03` / `0x01` | JPEG mode 3 / 量化设置 |
| `0x3808..0x380B` | 参数生成 | main 配为 640×480 |
| `0x380C..0x380F` | 参数生成 | main 总时序 2844×1968，不据此宣称实际 FPS |
| `0x3035` / `0x3036` | `0x11` / `0x69` | PLL 配置；不可照搬到不同 XCLK 的模组 |

这些 JPEG 使能位与 [Linux v6.12 OV5640 驱动](https://github.com/torvalds/linux/blob/v6.12/drivers/media/i2c/ov5640.c#L2893)
一致，因此从配置意图判断 camera44 是 JPEG 例程；实际输出仍需 SOI/EOI 抓取验证。
同一上游驱动的 mode 3 时序说明：数据按 HREF 行分段，尾行可能更短，帧内行数可变。
不能假设 JPEG 的每一行或最后一包固定长。
这里仅对照寄存器含义，不移植 Linux 驱动，也不引入 PetaLinux。

`ov5640_jpeg_cfg()` 仅在头文件声明，没有实现/调用；JPEG 设置已经在 `ov5640_init()` 内，
不能因此误判为漏调 JPEG 初始化。
FPGA42 则设置 `0x4300=0x61`、`0x501F=0x01`、`0x3821=0x01`，是 RGB565；
表中同样有 `0x4713=0x03`，这一行独自不能证明 JPEG 已启用。

## 4. 官方数据路径与本项目的边界

```text
PCLK: DVP → ov5640_data_8b → Video In to AXI4-Stream（内置异步跨域）
100M:                         → 4096×8 AXIS FIFO → simple AXI DMA S2MM
                                                       ↓ HP0
PS:                                           DDR → lwIP → GEM0
控制: GP0 → DMA AXI-Lite、GPIO FIFO 读计数；EMIO → SCCB
```

`ov5640_data_8b` 只延迟数据/HREF/VSYNC、等待启动帧，不检查 `FF D8`/`FF D9`、最大帧长或丢帧。
`WAIT_FRAME=10` 时，计数到 10 后下一次 VSYNC 上升沿才置 `wait_done`，不是恰好第 10 次即放行。
RESET_N 恒为 1、PWDN 恒为 0；初始化失败不会经此 IP 保持摄像头/采集复位。
IP 仓库与打包副本的这份 RTL SHA-256 相同：
`fe1de7a86826e7061c9955a11933ec6b4efff935c88264fcd042efe835d3e417`。

这里的 Video IP `TLAST` 是行结束，不是 JPEG 帧结束。
[生成网表](../board/vendor/ZYNQ_Vitis_7020/44_ov5640_ps_eth_udp_pc/ov5640_ps_eth_udp_pc.ip_user_files/bd/system/ip/system_v_vid_in_axi4s_0_0/system_v_vid_in_axi4s_0_0_sim_netlist.v:1492)
直接由 active_video 下降沿形成 `eol` 并进入 AXIS TLAST；FIFO 保留它。
这也符合 [AMD PG043 接口定义](https://docs.amd.com/r/en-US/pg043_v_vid_in_axi4s/AXI4-Stream-Interface)。
所以把该 TLAST 原样接 DMA 得到的是 HREF 行段，不能声称得到一整帧 JPEG。
M03/M04 必须按 JPEG 标记/帧状态产生本项目的帧级 TLAST。

AXIS FIFO 自身使用同一个 100 MHz 时钟，异步跨域是在前面的 Video IP 中完成的。
生成 DMA 网表为 8-bit S2MM stream、32-bit memory、无 DRE、无 SG、非 Micro DMA，
`C_SG_LENGTH_WIDTH=14`（单次长度上限 16383 字节），而 BD/Tcl 没有显式指定长度位宽。
迁移时必须重新检查生成配置；2 MiB 整帧上限至少需要 22-bit BTT，不能依赖 IP 默认值。
长度位宽含义见 [AMD PG021 参数说明](https://docs.amd.com/r/en-US/pg021_axi_dma/Field-Descriptions)。

## 5. 移植前必须修正的源码问题

| 位置 | 已观察的事实 | 本项目需要 |
|---|---|---|
| `emio_sccb_cfg.c:sccb_ack` | 主机主动驱动 SDA=0 生成第九拍，没有读取从机 ACK | 释放 SDA、检查响应、有限重试；明确错误状态 |
| `ov5640_init.c:sccb_read_reg16` | 用 STOP+START 分开地址写与读，读后也调用驱动 ACK 的函数 | 与目标模组规范核对；实现并仿真重复 START/读结束处理 |
| `main.c` 初始化 | 摄像头失败仍继续；忽略 DMA、GIC、网络等初始化返回值 | 失败阻止采集，不在无效配置上继续运行 |
| `axi_dma.c:axi_dma_start` | 先启动 S2MM，随后 Flush RX；完成后没有 Invalidate | RX 交给 DMA 前做缓存维护，完成后 CPU 读前失效；缓冲区独占缓存行 |
| `main.c` / `udp_perf_server.c` | 请求 1031 字节，固定发送 1024；`len` 被忽略，不读取实际 DMA 长度 | 完成时读取实际长度，只发送有效数据；验证尾行/尾片 |
| DMA 错误/启动失败 | IRQ 设置 `error` 后主循环不处理，启动标志可能一直为 1；无传输超时 | 错误、超时、复位完成都进入统一恢复路径，计数并释放所有权 |
| DDR 地址/所有权 | 单个 RX 地址 `0x01400000`，链接脚本没有显式预留该 DMA 区域 | 预留并对齐两个帧缓冲，不覆盖程序、栈、堆或发送中数据 |
| UDP 发送 | PCB 创建/绑定失败不能传回 main；部分失败后 PCB 失效；发送错误未统计 | 失败退出初始化；检查 pbuf/copy/send 返回值 |
| lwIP 循环 | camera44 未调用平台定时器初始化/fast/slow timer，只有输入轮询 | M01 用当前 lwIP 平台模板，TCP 控制必须获得定时器服务 |
| FIFO/帧边界 | 没有可靠的完整帧、溢出、整帧丢弃协议 | M03～M05 明确错误帧不送入后续加密/发送 |

证据入口：[main.c](../board/vendor/ZYNQ_Vitis_7020/44_ov5640_ps_eth_udp_pc/vitis/ov5640_ps_eth_udp_pc/src/main.c:96)、
[SCCB](../board/vendor/ZYNQ_Vitis_7020/44_ov5640_ps_eth_udp_pc/vitis/ov5640_ps_eth_udp_pc/src/emio_sccb_cfg/emio_sccb_cfg.c:146)、
[DMA](../board/vendor/ZYNQ_Vitis_7020/44_ov5640_ps_eth_udp_pc/vitis/ov5640_ps_eth_udp_pc/src/axi_dma/axi_dma.c:79)、
[UDP](../board/vendor/ZYNQ_Vitis_7020/44_ov5640_ps_eth_udp_pc/vitis/ov5640_ps_eth_udp_pc/src/udp_perf_server.c:19)。
1031/1024 的差异说明程序没有证明有效长度，不据此断言每次必然丢 7 字节；
提前 TLAST、实际 HREF 段长以及缓存状态均会影响结果，需要仿真/抓取。

本机 `axidma_v9_20/examples/xaxidma_example_simple_intr.c` 的顺序是启动前 Flush、
完成后检查数据前 Invalidate，可作为驱动级参考。
[PG021 S2MM_LENGTH](https://docs.amd.com/r/en-US/pg021_axi_dma/S2MM_LENGTH-S2MM-DMA-Buffer-Length-Register-Offset-58h)
明确规定：simple DMA 完成后此寄存器更新为实际写入字节数；启动容量必须容纳最大接收包。
因此 M05 不需要先引入 SG 来获得变长帧长度，但要在重新启动之前记录长度/状态，并通过短包测试确认。

FPGA42 的 SCCB RTL 会读 ACK，并支持重复 START 和最后字节 NACK，比 PS bit-bang 更适合作时序参考；
但顶层把 ACK 悬空，配置器读 ID 后不检查值，而且使用逻辑分频时钟与主动驱动高电平。
不能不经审查直接作为 M02 完成品。
其 `img_data_pkt` 是 640×480 RGB 行分包（首包 1288、后续 1280 字节），FIFO full/empty 未使用，
自定义帧头与 EYEPQC 协议不同；不复用其整条发送链路。

echo 的 UART 文案说端口 6001，但 [实际代码绑定 7](../board/vendor/ZYNQ_Vitis_7020/40_lwip_echo_server/vitis/lwip_echo_server/src/echo.c:100)。
该接收回调只处理 `p->len` 而非整条 pbuf 链，sndbuf 不足也释放数据，不能直接当作可靠 TCP 控制接收器。
SCU Timer 例程硬编码 667 MHz 假设；M01 应使用 BSP 实际频率。
echo 的平台已占用私有定时器/GIC，后续不要再初始化第二套并覆盖已有中断注册。

## 6. 最短迁移路线与尚未通过的门禁

1. 核对实物 DDR/板卡版本，以 hello/echo 的 PS 配置重建最小 BD；先不接摄像头和 DMA。
2. 用本机 Vitis Python API 和当前 Standalone/lwIP 模板，生成 UART、DDR 自检、定时器/LED、GEM echo。
3. 完成 M01/G0 的重建和 30 分钟冷启动运行，留存日志，再做 M02 ACK/ID/JPEG 初始化。
4. M03/M04 按 SOI/EOI、变长、背压/溢出建模；M05 先用固定短包发生器验证 DMA 长度和缓存，再接摄像头。

本机为 Vivado/Vitis 2026.1，旧 `system_bd.tcl` 的版本守卫拒绝直接运行。
本机 IP 目录包含 PS7 5.5、DMA 7.1、AXIS FIFO 2.0，但 Video In 已为 5.0，官方 BD 引用 4.0。
不能仅删版本检查就宣称迁移成功；需重建/升级并检查接口、默认参数、地址、复位、时序。
2026.1 已禁用 XSCT，驱动的 SDT 配置查找和中断接口也应以新 BSP 为准，不拷贝旧生成 BSP。

本次额外验证：Icarus `-g2012 -tnull` 对官方 `i2c_dri` 和 `ov5640_data_8b` 两个独立顶层
语法/展开检查通过。这不是 SCCB/DVP 功能仿真，不能代替 M02/M03 完成判据。
`git hook run pre-commit` 通过：5 份向量可复现、M00 10 项测试通过。
导入脚本 PowerShell 语法检查和本报告本地源码链接检查通过。

最初研究结束时未生成新 XSA/bitstream；后续补装器件支持并完成 M01 离线构建，见下节。
原始源码未改写、未下载到板卡，M01/G0 仍未通过。

## 7. 新增硬件资料与海力士配置核对

2026-09-27 新增的硬件资料包中，硬件目录为 `3_开发板原理图和硬件相关文件`，
以下原始文件只读，未混入源码：

| 文件（相对硬件目录） | SHA-256 |
|---|---|
| `ZYNQ7010_7020核心板原理图_2V5.pdf` | `1c8cf8105e91d762d29ad604e82b629b3921fa474d5a0311ed6c04237db107ea` |
| `领航者ZYNQ底板原理图_V3.9.pdf` | `ec8b68eeb07e0743e6c60528444f6aeb457dc60e897ddf9eb86d5a56c1ab6a69` |
| `硬件相关文件/核心板信号走线长度/ZYNQ7010_7020核心板信号走线长度.csv` | `574e22fe8f4fe40bc406b499d03b8b81ebadcaecaa09020fa0a05008da9e2f2b` |

核对 PDF 的原理图连接，不仅依赖文本提取；关键页已渲染到忽略的 `tmp/pdfs/`。
核心板改版说明称 V2.5 相对 V2.4 优化电源时序、连接器引脚兼容；该说明不证明
用户实物的具体版本、替代料或供电测量结果。原理图事实如下：

- 核心板第 4 页：PS 时钟 33.333333 MHz，UART0 MIO14=RX/MIO15=TX；
  GEM0 MIO16..27，MDIO MIO52/53；MIO Bank0=3.3 V、Bank1=1.8 V。
- 核心板第 5/8/10 页：DDR/PS DDR Bank502 供电 1.35 V，U3/U4 两颗 x16，
  地址 A0..A14、BA0..BA2，32-bit 共享单 rank；图中芯片是 NT5CC256M16。
- 底板第 2 页：SD0 经 TXS02612 电平转换到 SD 卡，MIO40..45 与 MIO10 卡检测
  对应官方 echo preset。M01 已补齐 SD0，以便同平台 FSBL 支持 SD 冷启动。
- 底板第 6 页：USB UART 为 CH340C，P5 的 1–3、2–4 接 PS UART；板上标注的
  UART1 是连接器名称，接核心板 MIO14/15（软件 PS UART0）。另一侧是 UART3/PL。
- 核心板第 11 页：PS PHY 为 YT8521SC-CA、RGMII 1.8 V、复位连接 PS_POR_B；
  底板还有独立 PL PHY YT8531，不能把 PL 网口当作 M01 的 PS GEM0。

用户确认实物为两颗 `H5TC4G63EFR-RDA`。对照
[SK hynix Rev.1.3 数据手册](https://datasheet.lcsc.com/datasheet/pdf/aea45ff70742b3df7465cb4aa7642654.pdf?productCode=C37953994)，
每颗 4 Gb / x16，合计 1 GiB / 32-bit；533 MHz 用非可选的 CL8/CWL6，
保守 tRCD/tRP=15 ns、tRAS=36 ns、tRC=51 ns、tFAW=50 ns。
本地原始手册 `tmp/pdfs/h5tc4g63efr.pdf` SHA-256：
`7395cdfc47e3d3eed193b54f21b756f5c356623822f57cf54aca8f2b7cc97ba7`。
`prj/build_m01.tcl` 使用 Custom 时序、显式 CLG400，封装长度来自本机
`Vivado/data/PS/7series/data/zynqconfig/part/partno_preset.xml` 中
`xc7z020clg400-2` preset（CK=80.4535），而非照搬旧 BD 的 54.563（对应 xc7z010）。
PCB 延迟仍保留示例值，走线 CSV 的实际版本适用性待核对，不声称已完成校准。

网络迁移新增风险：实际读取官方压缩包内 echo 的
`lwip211_v1_3/src/contrib/ports/xilinx/netif/xemacpsif_physpeed.c`，
并对照本次生成的 lwIP 2.2.0 同名文件，两者均无 YT8521 分支，未知型号进入
Marvell 初始化。新资料中的 Motorcomm YT8521 数据手册第 39/47 页给出
PHY ID `0x0000:0x011a` 与状态寄存器 `0x11`，模式/延迟控制则为扩展
`0xA001/0xA003`，不能仅改厂商 ID 后沿用 Marvell 的寄存器写入。
按此风险先做型号适配再下载；新适配只注入生成工作区的共用 PHY 分派，
双 ID 校验、保留 1.8 V strap、RX 2 ns/TX 1.95 ns（保留校准参数），
有界 reset/协商及重连失败检查，不安装 PetaLinux，也不复制整个旧 BSP。

用户补充 CF7020B / COM4；规格书 V1.2 第 10–11 页将 CF7020B 对应到 7020 核心板，
它是型号而非 PCB 修订号，不能直接据此确认走线 CSV 对应实物。
当前实际结果：JTAG 已临时下载；COM4 读到 UART 启动、DDR scratch 及定时器正常日志。
实际 MDIO 确认 YT8521 ID `0000:011A` / 地址 7，配置 `0x8160`。
海力士配置的新 BD/bitstream/XSA、对应 ARM ELF 与 SD0/同平台 FSBL 离线构建通过。
已按同一新 XSA 重新构建并下载含 PHY 适配的软件，细节与输出哈希见 `doc/m01.md`。
用户确认尚未连接 PS 网口，当前 link=0 / 协商超时符合接线状态；ping/echo 尚未验证。
尚未修改 PC 网卡或写 SD/Flash，也未完成冷启动 30 分钟验收。
