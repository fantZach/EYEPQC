# Implementation progress

更新：2026-09-29。实施依据 `doc/steps.md`，采用 Ponytail：复用密码库与标准库，
以能运行、能比对的最小链路推进，保留必需的长度检查和认证边界。

## 当前状态

| 步骤 | 状态 | 产物/证据 |
|---|---|---|
| 立即清单 1：目录与忽略规则 | 完成 | src/rtl、src/ps、src/host、sim、data、board、report、skill；build 生成目录已创建并忽略 |
| 立即清单 2：官方资料与工具 | 源码研究完成，实物待确认 | 已提取 8 个官方工程并记录压缩包 SHA-256；XPR/BD 为 2020.2、xc7z020clg400-2；发现 DDR3/DDR3L 配置差异 |
| M00：协议与黄金参考 | 完成（主机离线验证） | C/Python 协议实现、标准/随机/篡改向量、独立 GHASH 中间值和复现脚本 |
| M01 / G0 | 部分上板通过、门禁未通过 | UART、DDR、定时器已验证；USB0 从机独立探针 30 秒 16.37 MB/s、30016 块逐字节正确；LED/冷启动及 USB 视频整机仍待验收，见 [USB 探针](../doc/usb_probe.md) |
| M06 / 固定图片 MVP | M06 判据完成；PS/PL 混合图片 MVP 已上板通过 | GitHub secworks/aes、AXI4-Lite、PL AES / PS GHASH；13 向量、同 Key 连续块/更新/硬复位通过，53 周期/块；IP 综合 2600 LUT/2566 FF/0 BRAM；完整 JPG/512 KiB PNG 认证往返通过；非 M08 全 PL |
| M02：SCCB 摄像头配置 | RTL/仿真/实现通过；完整物理门禁待验收 | ID=5640；复电后串行 40/40 配置成功，M05 再完成实拍；历史 4300 超时原因及 20 次真正冷启动/ILA 仍待验收 |
| M03：DVP/JPEG 采集 | 独立仿真/OOC 综合通过，M05 集成实拍通过 | 仿真 1000 帧逐字节及故障恢复；与 M04/DMA 集成后上板实拍 1000 帧，未单独完成 DVP 输入 IO 时序验收 |
| M04：异步 FIFO/AXIS | 原生仿真/OOC 综合通过，M05 集成实拍通过 | 三配置各 1000 帧仿真；与 M03/DMA 集成后上板实拍 1000 帧，无丢帧/溢出；默认 64 KiB 帧上限 |
| M05 / G1 功能判据 | 完成 | 缓存开关各 10000 次 DMA 和错误恢复通过；OV5640 1000 帧实拍、末帧 JPEG 解码通过；平均 6277.23 bytes、最大 6331 bytes、约 7.48 fps |
| M07：GF(2¹²⁸)/GHASH | 独立 RTL/仿真/OOC 综合完成，已被 M08 复用 | 32 组 GF 乘法、80 组 M00 轨迹和 20 组 NIST 向量逐块通过；891 LUT/1037 FF、0 BRAM/DSP |
| M08：AES-GCM AXIS IP | RTL/仿真/OOC 综合及 G2/G3 DMA 上板完成 | 102 组端到端、随机背压及异常/零化通过；6370 LUT/5679 FF、0 BRAM/DSP（OOC） |
| G2：固定 DDR→DMA→M08→DMA→DDR | 完成 | 21 组 0～1400 字节板测与主机黄金参考、认证解密一致；S2MM 延迟启动形成背压；布线 WNS +0.107 ns、WHS +0.044 ns，见 [G2](../doc/g2.md) |
| G3：实拍 JPEG→DDR→M08→DDR | 功能及板端 45 fps 目标完成 | 快速模式 1000 帧 320×240：47.172 fps；1000 帧 640×480：47.168 fps；均无计数丢帧/溢出，末帧认证解密、画面可辨；新布线 WNS +0.013 ns、WHS +0.018 ns，见 [G3](../doc/g3.md)。USB 端到端视频仍待 G4/G5。 |
| M09：ML-KEM-512 PS 基线 | 完成离线及 A9 上板 | mlkem-native v1.3.0；PC ACVP 25/25/10 组、A9 3×1000 次；Decaps 约 11.929 ms、7.953 M 周期、栈约 12,860 B、堆 0，见 [M09](../doc/m09.md) |
| M10 | 离线与 JTAG 板测完成 | 双向 Finished、认证重协商、重放拒绝和清零通过；真实 USB 控制握手待 M11/G6，见 [M10](../doc/m10.md) |
| M12 离线回放 | 完成离线部分 | 实拍 G3 多包密文认证解密、JPEG 解码/保存及篡改/截断拒绝；实时 USB 接收仍待接入，见 [M12](../doc/m12.md) |
| M11 USB 固定内容 | 中间门禁通过 | 30 秒 30519 条协议记录、1.442 MB/s；实拍 640×480 JPEG 经 USB 往返 10 包逐字节一致且解码；摄像头直发 G4 待做，见 [USB 探针](../doc/usb_probe.md) |
| M12 USB、M13～M15 / G4～G7 | 未开始 | M12 实时 USB 接收/显示未集成；M14 仍为全门禁通过后的可选优化 |

2026-09-29 USB 方案变更：用户连接 USB Slave 后，CF7020B 经 JTAG 运行 CDC ACM 探针，
Windows 枚举为 COM7；30.047 秒收到 491,782,144 字节完整校验块（16.367 MB/s），
无序号或字节错误。`doc/goals.md`、`doc/steps.md`、`doc/protocol.md` 已将第一版传输
改为 USB0 字节流，历史以太网例程与验收记录保留作参考。真实视频 G4～G7 尚未通过。

板级资料已解压并完成源码研究；用户已提供 DDR 型号/颗数，新增原理图已核对。
已临时 JTAG 下载并采集 COM4；用户确认 PS 网口未连接，G0 网络和冷启动验收保留待办。
M00 与官方研究已提交为 `e649634`；M01 为 `1a05778`，不包含官方例程或生成产物。
本次按用户要求改写 `doc/steps.md` 优先级，先完成不依赖网口/摄像头的图片 AES MVP，
复现与当前验证状态见 [图片 MVP](../doc/aes_mvp.md)。

最新顺序调整（2026-09-27）：用户要求以太网配置放到 `doc/steps.md` 最后编程阶段。
PS GEM/PHY/IP、接线、ping/echo、M11、M12 联网接入及 G4～G7 统一后置；
当前 M02～M09 独立实现及 G2/G3 功能判据已完成；接下来推进 M10 本地验证、
M12 离线回放，网络配置仍后置。
未接网口不再阻塞独立模块编写/仿真；LED/复位/冷启动要求保留，完整 G0 仍未通过。
已启动的 `m01_g0_reset_1` 仅作本地复位修正基线重建，不下载网络程序、不改网卡或 SD。

## 已实现

- 网络字节序的 40 字节 UDP 包头，1400 字节最大载荷、2 MiB 最大 JPEG、精确分片/数据报检查。
- 12 字节 Nonce（32 位 epoch + 64 位 sequence）；12 字节 TCP 控制前缀及各类消息长度限制。
- TCP 拆包/粘包、保留位、版本、套件、错误码与 UTF-8 校验；默认禁止明文视频降级。
- 可移植 C99 序列化与解析，不需要 OS、动态内存或非对齐结构体访问。
- cryptography AES-GCM，加密/认证解密与独立 GF(2^128)/GHASH 逐块模型。
- kyber-py 离线 FIPS 203 参考，固定测试种子与内部 Encaps 输入，可复现 KeyGen/Encaps/Decaps。

M00 的格式验证不是完整会话安全实现。KDF/Finished/命令 MAC/重放窗口在协议文档中约定，
具体状态机待 M10/M11；组帧、认证后显示和回放待 M12。Python KEM 教育库不用于生产握手。

## 验证记录

环境：Windows，Python 3.12.10；cryptography 48.0.0、kyber-py 1.2.0、
cffi 2.1.1、pycparser 3.0；主机 gcc 16.1.0。

运行 `sim/scripts/run_m00.ps1`：5 份向量文件与 SHA-256 清单可复现，10 项测试全部通过。
覆盖 20 组 NIST AES-GCM（AES-128/96-bit IV/128-bit Tag）；
NIST ACVP v1.1.0.35 的 ML-KEM-512 KeyGen 25、Encaps 25、Decaps 10，含隐式拒绝测试。
固定 SHAKE256 测试输入生成 56 组边界与 24 组随机 AES-GCM 向量，
39 组保存的篡改样本，另逐位翻转一个 17 字节明文、40 字节 AAD 样本的
Key/Nonce/AAD/密文/Tag，共 808 次认证失败检查。
1000 组随机包头通过 C/Python 字节比对，包含不对齐输入/输出、32/64 位数值、明文/加密及尾片。
包括标准向量数量与哈希、EOF 半包、超长消息、截断数据报、UTF-8 和缓冲区容量检查。

C 使用 `-std=c99 -Wall -Wextra -Werror -pedantic` 编译通过；
也使用本机 Vitis `arm-none-eabi-gcc` 以 `-mcpu=cortex-a9 -marm` 编译为 ARM 裸机对象通过。
这是协议模块的编译验证，不代表已生成/运行完整裸机应用。
`pip check` 通过。测试时间仅代表主机软件自检，不作为 PL/网络性能结果。

NIST 原始 GCM ZIP 请求遭 HTTP 403/传输失败，导入脚本使用 pyca 上游保存的原始 CAVP `.rsp`，
固定提交 `8e03e30e3aae01632a697e903e3593c924f0139d` 并核对 SHA-256。
ML-KEM 直接取 NIST ACVP 提交 `65370b861b96efd30dfe0daae607bde26a78a5c8`，
原始 URL、文件哈希和筛选结果见 `data/kat/sources.json`。

## M01 实现与待完成门禁

用户提供的资料实际位于 `D:/BaiduNetdiskDownload/4_Source_Code`（不是 `4/_Source/_Code`）。
已读取压缩包索引与源码说明，发现 `1_FPGA_Design/ZYNQ_7020_FPGA.rar`（1,519,052,295 字节）
和 `2_Embedded_Vitis/ZYNQ_Vitis_7020.rar`（2,249,047,175 字节）。
包含 `42_ov5640_udp_pc`、`1_hello_world`、`8_uart_intr_loop`、`9_timer_intr_led`、
`40_lwip_echo_server`、`44_ov5640_ps_eth_udp_pc`；源码说明标注从 2018.3 升级到 2020.2。
已通过 `prj/import_vendor.ps1` 提取 30 个 FPGA、2237 个 Vitis 文件，清单全部存在。
详见 [官方例程研究](vendor_examples.md)，核心结论：

- hello/echo 等配置 DDR3L MT41K；camera 配置 DDR3 MT41J，不能混用未经实物确认的 PS 配置。
- 两个摄像头工程的引脚一致；PCLK 约束为 25/72 MHz，仍需按实际模组配置测量。
- FPGA42 是 RGB565/PL 网络；Vitis44 的初始化确实启用 JPEG/PS GEM。
- Video In 的 TLAST 是 HREF 行结束，不是 JPEG EOI；必须补 M03/M04 帧级边界与错误恢复。
- camera 示例存在 SCCB 无 ACK 检查、DMA 1031/UDP 1024 长度不一致、缓存维护顺序及错误恢复问题。
- 旧生成 DMA 长度位宽为 14，不能容纳 2 MiB 整帧；simple DMA 的实际长度可从完成后的 S2MM_LENGTH 读取，后续先仿真/短包验证。

资料研究阶段原始官方源码未改写，也未下载实物板卡；后续 JTAG/COM4 验证见下文。
官方 SCCB/采集两个独立 RTL 顶层的 Icarus 语法/展开检查通过（不是功能仿真）。
M00/官方研究提交前 hook 通过，M00 10 项测试通过。

本次新增，详细说明见 [M01 构建与上板](../doc/m01.md)：

- `prj/build_m01.ps1/.tcl/.py`：独立 PS7 BD、100 MHz PL LED 心跳、同步复位、实现/XSA、
  Vitis Python Standalone/lwIP 构建；全新目录，不覆盖旧产物，不下载板卡。
- `src/ps/src/m01.c`：UART、统一状态/始终启用的应用断言、异常、SCU tick 与全局计时器检查；
  64 KiB 自有 DDR scratch 的非缓存/缓存读写；周期自检与统计；静态 IPv4 ping/TCP echo。
- echo 检查完整 pbuf 链，发送空间不足时保留给 lwIP 重试，处理 FIN 关闭重试及连接计数。
- `src/host/m01_probe.py`：标准库 echo 长包/分段读/重连探针，默认 1800 秒；失败不静默重试。
- `sim/scripts/run_m01.ps1`：四项离线测试通过（含实际 PHY C 模型）；M00 十项回归通过；pre-commit 增加 M01 校验。

历史构建（补装前）：Vivado 2026.1 识别有效 BASIC 许可证，但 `get_parts xc7z020clg400-2`
为空，安装目录缺少 Zynq-7000 器件支持。脚本在创建项目之前明确失败，未用其他器件替代。
当时没有新 BD 验证、综合、实现时序、bitstream 或 M01 XSA 的成功结果。

为继续软件验证，单独提取官方 echo 的 `vitis/system_wrapper.xsa` 到忽略的 `build/reference/`，
SHA-256 为 `0e27f6285f61cd8b56d7f3bf2fa2da309ce8ad1f87a20d2796d59709650f43d6`。
实际运行 Vitis Python 脚本成功建立 Standalone、lwIP 2.2.0 BSP、FSBL 和 M01 Cortex-A9 ELF，
应用 `-Wall -Wextra -Werror` 编译通过；上游 BSP/旧 XSA 生成代码仍有警告，不当作板级通过。
最终参考工作区 `build/vitis/m01_reference_final/`，清单记录输入/源码/ELF 哈希。
参考 ELF 的 DDR scratch 起始 `0x00200080`、64 KiB，与栈及其他 BSS 分离。
DDR 测试只覆盖 scratch，不是全内存压力测试；应用测试和 localhost 探针不代表真实网口通过。

后续实际验证（2026-09-27）：用户已安装 Zynq-7000 器件支持，
`get_parts xc7z020clg400-2` 成功；两颗 H5TC4G63EFR-RDA 配为 1 GiB / 32-bit、
Custom DDR3L-1066、CL8/CWL6。独立新工程 `m01_hynix_sd` 的 BD、综合、实现、
bitstream/XSA、对应 Standalone/lwIP BSP/FSBL/ELF 全部成功，未回退到参考 XSA。
PL 时序 WNS 6.068 ns / WHS 0.130 ns / WPWS 4.146 ns，DRC 0 项；
25 LUT、60 FF、0 BRAM/DSP，LED 外部 output-delay 提示仍留存。
SD0 及 setup/hold 失败检查已加入并验证；新 FSBL 实际链接 `InitSD` 与同平台
`ps7_init`，新 ELF scratch 为 `0x00200080` / 64 KiB，与其他对象和堆栈分离。
产物哈希见 M01 文档，清单 `board_validated=false`，未创建/写入 BOOT.BIN。
应用继续使用 BSP/lwIP，按 Ponytail 不引入新驱动框架或依赖。

新增资料目录 `D:/BaiduNetdiskDownload/正点原子领航者` 已核对，核心板 V2.5
原理图标明 DDR 1.35 V；图中 PS PHY 为 YT8521SC-CA，而旧官方/新 AMD lwIP
均无对应型号分支，不能盲用 Marvell 初始化。原理图、走线 CSV 与哈希见
[官方例程研究第 7 节](vendor_examples.md)。用户确认 CF7020B / COM4；规格书可对应
该型号，但不等同于已经确认 PCB 为 V2.5。实际 MDIO 读到 YT8521 `0000:011A` / 地址 7；
已加入双 ID 分派、铜口/电平校验、RGMII 延迟和有界 reset/协商，不改官方源码或全局 BSP。
临时 JTAG 下载成功，UART 启动、64 KiB DDR scratch 非缓存/缓存及 60 秒复测通过，
50 ms tick 正常；已采集至应用 sec=70，DDR/异常/断言/滞后均为零。网络 PHY link=0，
未通过 ping/echo，LED 频率仍需实物确认。当前 PC 有线网卡在 10.179.236.247，
与板卡静态 192.168.1.10 不同网段，未擅自修改网络设置。

原定下一步：确认 PS 网口接线/地址 → 实际 ping/echo、LED 验证 →
基于同平台 SD 冷启动运行 30 分钟 → 确认 G0 后进入 M02。
已易失性 JTAG 下载；未写 SD/Flash。用户确认 PS 网口未连接，协商超时符合当前接线状态。
最终软件为 `m01_cf7020b_v2`，原始日志/输出哈希见 M01 文档。

## 提前执行：M06 / 图片 AES MVP

用户于 2026-09-27 要求先完成 AES 加密图片，并采用 GitHub 开源核。
复用 `secworks/aes` 提交 `80dc4718e1dcbbdb4b0dd1bdb393d8f7b98981dc`，
保留 BSD-2-Clause/原始版权；接口固定 AES-128 Encrypt。原生 GP0/AXI 协议转换器
连接最小 AXI4-Lite 寄存器，PS 调度实际 PL AES，PS 软件 GHASH 保留完整 GCM 认证。
无新依赖、摄像头、DMA、网络、ML-KEM 或非易失启动写入。

独立 RTL 仿真：1 个 NIST AES 块与 12 个确定性随机块，通道错开/背压、WSTRB、
非法访问、忙时拒写与上游轮密钥/状态零化通过。实际可移植 C 模块对照 80 个 M00、
20 个 NIST GCM、5 个长输入向量通过；主机 mailbox 认证、超长/截断与故障清理通过。

首次 `aes_mvp_1` 原生 BD/综合/实现/XSA/ELF 构建成功，100 MHz 时序通过，
但上板和一次断电重试在启动后 DAP 超时，未取得图片加密结果。
生成 reset IP 明确显示辅助复位 `C_AUX_RESET_HIGH=0`，输入却接常量 0，
导致 PL 永久复位；旧 M01 的 UART/DDR/定时器结果不受此问题影响，
但从未通过的 PL LED 实测不能据此认定成功。
共享板级 Tcl 已显式配置外部低有效、辅助高有效并增加实际 BD 属性断言；
M01 离线测试增加极性配置回归（共 5 项）。修正硬件 `aes_mvp_2` 已构建并上板验证。
旧 M01 硬件也需要重新构建后再验收 G0；其历史产物和日志保留，不覆盖。

原 64 KiB ELF 已在 CF7020B 上实际完成：9373 字节 PNG 两次运行、65536 字节上限 PNG 一次，
独立主机认证解密与原文件逐字节及 SHA-256 一致，五类篡改均被拒绝。
用户新提供的 JPG 为 365954 字节；软件缓冲区扩至 512 KiB，复用已验证 bit/XSA，
只重新构建 `aes_mvp_3` 软件。空闲/JTAG 时禁用 DCache，PS 独占处理时启用，
完成后刷新/关闭再发布结果；不压缩、不裁剪原图。完整 JPG 实测通过，全部字节及 SHA-256
一致：`f7ebf2bd3af8a998c5afd155982faa576be6bc8e1babde5ec1dfb2b7f19d5650`。
板端近似耗时 4652657 us（不含 JTAG 传输），五类篡改拒绝、板端密钥/Nonce 零化检查通过。
512 KiB 合法 PNG 上限也实测通过，板端近似耗时 6820005 us。
日志/清单/图片保存在 Git 忽略的 `data/captures/aes_mvp_userjpg_1/`、
`aes_mvp_boundary_512k/` 和 `aes_mvp_userjpg_uart_1.log`，完整复现及产物哈希见 MVP 文档。
Vivado 100 MHz 时序 WNS 0.767 ns / WHS 0.089 ns，2987 LUT / 3094 FF，无 BRAM/DSP。
无摄像头/网口/全 PL GHASH 或视频吞吐验收，G0 和正式后续门禁仍未通过。

### MVP 性能优化

用户要求优化 4.65 秒的板端处理。未换 AES 核或重建硬件；Vitis 明确启用并核对 `-O2`，
GHASH 改为固定循环的 32-bit 字运算，无秘密索引表或未对齐整数强转。
同一原始 JPG：`-O0` 4652657 us → `-O2`/byte GHASH 512107 us →
`-O2`/word GHASH 首次 239584 us。AES/MMIO 调用 22875 次约 51039 us，
PS 其余约 188544 us（含 GHASH/CTR/XOR/初始化/探针，不是纯 GHASH）；仍不是 15 fps 验收。
第一轮软件 `build/vitis/aes_mvp_o2_word_1`，构建清单新增真实优化级别与构建脚本哈希；
旧记录保留。同图三次 239584 / 239072 / 239584 us，中位数 239584 us，约快 19.42 倍，
板端约 12.22 Mbps / 同等大小 4.17 张每秒；不是视频或 15 fps 验收。
512 KiB 上限 342481 us，也通过认证、密文/Tag/全部字节比对、SHA-256、五类篡改与密钥清理。
原始 JPG 未压缩/裁剪；105 组离线黄金向量及全部 18 项 hook 检查通过。
日志为 `data/captures/aes_mvp_word_profile_uart_1.log`，结果为 `aes_mvp_word_jpg_1..3/`
和 `aes_mvp_word_boundary_1/`，均 Git 忽略；复现/计时边界见 MVP 文档。

第二轮仅将应用及 C 黄金向量检查改为 `-O3`，实际编译命令已核对；PS C/RTL 不变。
ARM 反汇编确认 GHASH 的 4-word 内层移位循环展开，主循环仍固定 128 次；
ELF text 增加 1008 字节，data/bss 不变，无新依赖、秘密索引表或手写汇编。
同图三次 153440 / 153437 / 153401 us，中位数 153437 us，比第一轮再快 1.56 倍，
比最初快 30.32 倍；AES/MMIO 49984 us、PS 其余 103453 us，不含 JTAG/最终缓存刷新。
板端约 19.08 Mbps / 同等大小 6.52 张每秒，仍未通过 15 fps 或完整视频验收。
512 KiB 上限 219779 us；四次认证/全部字节/SHA-256/五类篡改/板端密钥清理均通过。
105 组 C 黄金向量及全部 18 项 hook 检查通过，当前软件 `build/vitis/aes_mvp_o3_word_1`。
证据为 `data/captures/aes_mvp_o3_profile_uart_1.log`、`aes_mvp_o3_jpg_1..3/`、
`aes_mvp_o3_boundary_1/`，不提交图片、日志或密钥；第一轮历史产物保留。

## 复现

```powershell
& ./sim/scripts/run_m00.ps1
& ./prj/check_environment.ps1 -ToolRoot 'D:/AmdDesignTools/2026.1'
& 'D:/AmdDesignTools/2026.1/gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe' -mcpu=cortex-a9 -marm -std=c99 -Wall -Wextra -Werror -pedantic -I src/ps/include -c src/ps/src/protocol.c -o build/vitis/protocol.o
```

新工作区请先按 README 建立 Python 环境，并创建忽略的 `build/vitis` 后执行交叉编译。

## Git 提交前校验

已加入 `.githooks/pre-commit`，本仓库设置 `core.hooksPath=.githooks`。
hook 顺序为暂存改动空白检查、生成向量一致性检查、M00 10 项测试。
实际执行 `git hook run pre-commit` 通过；注入不存在的 C 编译器后返回非零并拒绝提交。
当前顺序为暂存空白检查、向量一致性、M00 10 项、M01 5 项、图片 MVP 3 项、M02 4 项、M03 2 项和 M04 1 项离线测试。
M04 调用已安装 Vivado 的 XSim/XPM 原生模型，没有工具时明确失败，不以简化 FIFO 替代。
hook 校验工作区文件，不自动暂存、生成向量或创建 Git 提交；本次按用户要求暂存并提交图片 MVP。

## M02：代码/仿真与最小上板探针

`tb_heartbeat.sv` 曾移至 `sim/board/`，现按用户最新要求移回 `sim/tb/`，M01 原有回归不删除。
重写最小开漏 SCCB，复用官方 camera44 的 251 个有序寄存器事实，不复制旧 SCCB 驱动。
OV5640 先读 5640 ID，配置后检查 16 项关键寄存器；失败保持摄像头/采集复位。
支持分辨率、量化参数、HTS/VTS、JPEG/YUYV；时钟、超时、上电/复位延迟均可校准。
4 项离线检查覆盖引脚协议、来源事实、20 次模拟初始化、错误 ID/NACK/超时/读回篡改、
重配置/输入锁存与复位恢复、板级 GPIO 参数/状态映射。
独立综合 `m02_synth_1`：421 LUT / 250 FF，无 latch/BRAM/DSP；开漏 IOBUF 2 个，0 综合警告/错误。
模块的 OOC 综合会转换开漏 tri-state，已调整摄像头 BD 为整体综合，不将错误分块产物用于上板。
用户先确认摄像头未接、只做代码仿真，随后确认已连接；最小探针已实现/临时 JTAG 下载。
P2/上拉/IO 引脚已核对原理图，实际模组晶振不能由传感器资料确认；暂不驱动 W15 XCLK，
通过真实 ID/配置结果继续确认。不改网络、SD/Flash，也不把 GPIO 配置成功等同于 JPEG 采集通过。
完整接口、来源、命令和剩余物理门禁见 [M02](../doc/m02.md)。
有效硬件 `m02_board_2`：WNS 0.787 ns / WHS 0.051 ns / WPWS 4.146 ns，
882 LUT / 1082 FF，无 latch/BRAM/DSP，DRC 0 项，原生 SCCB IOBUF 2 个。
首次 run 0..6 ID/配置成功，run 7 在 4300 回读发生超时，保护正确退出；
未擅自增大超时或把该失败删除。复测同版硬件 run 0..19 全部通过，包含两个 JPEG 分辨率、
质量/VTS 切换，ID=5640；日志 `build/m02_board_2_jtag.log`、`m02_board_2_jtag_retry.log` 保留。
xsdb.bat 在 Tcl 报错后仍可能退出 0，新增最小 PowerShell 包装器验证本次成功标志，
离线注入零退出假失败的检查通过。首次间歇超时仍需 ILA 定位；真正断电冷启动 20 次、
JPEG 采集/FPS/PCLK 均未通过，未写 SD/Flash、未运行网络程序。

用户再次要求上板：复用同版/同哈希硬件及正式 PowerShell 包装器，
`build/m02_board_validation_20260927_1.log` 的独立首批 20/20 完整通过，
ID=5640、16 项关键回读、320×240/640×480 JPEG 和质量/VTS 切换均正常。
重复验证时本助手未等待第二个 XSDB 完全退出便启动第三个，导致两个会话重叠复位/访问；
`..._2.log` AP0 读回中断，`..._3.log` ps7_init/DAP 报错，这两批无效，不计入通过数。
所有相关进程已退出，后续访问严格串行；原生 DAP 复位恢复了 ARM 枚举但不能停核，
系统/核组复位仍超时（`..._4.log`、`..._5.log`、`..._dap_reset_2.log`、`..._core_reset.log`）。
用户已断电重启，ARM 调试恢复；随后严格串行执行两批，各 20/20，共 40/40 次传感器配置通过。
新日志 `build/m02_board_validation_20260927_after_power_1.log` 与 `..._after_power_2.log` 均有本次成功标志，
每次 ID=5640、error=0、16 项回读通过，覆盖两个 JPEG 分辨率及末次量化参数 12/VTS 2400。
这只有一次板卡断电重启，不是 20 次实物冷启动；历史 4300 超时未复现但尚未定位，完整 M02/G1 未通过。
没有改 RTL/参数、新增依赖、写 SD/Flash 或运行网络程序；详细日志哈希见 M02 文档。

## M03：按 steps 推进采集模块

用户撤回临时快照优先，恢复 M03 → M04 → M05 顺序；未建立 BRAM/JTAG 摄像头快照旁路。
新增 `dvp_capture.sv` 与 `jpeg_marker_check.sv`，PCLK 域采样有效字节，HREF 结束不当作 JPEG EOI。
保留 HREF/VSYNC 极性参数、异步置复位/同步释放、2 MiB 上限；记录无 SOI/EOI、异常 VSYNC、
空帧、超长和标记错误，错误后下一 SOI 恢复。输出暂属投机字节，下游必须整帧丢弃错误帧。
JPEG 长度段内的 FF D8/FF D9 不作为标记，熵段处理 FF00、restart/fill；不实现 JPEG 解码器。
已有 Icarus/标准库即可复现，无新增运行依赖。1000 帧真实自有 JPEG 激励逐字节通过，
包括 HREF 间隙、EOI 紧邻 VSYNC、正反极性、错误统计、最大长度边界和停 PCLK 复位恢复。
完整用户 JPG 365954 字节也作为输入激励：JPEG 到 EOI 为 365930 字节，尾部 24 字节不进入帧输出；
三帧及紧邻 VSYNC 的额外一帧比对通过。原文件不修改，AES MVP 的完整文件加密记录不变。
这不是实物摄像头采集，未改板上 M02 PL、SD/Flash 或网络；完整 M03/G1 未通过。
有效独立 OOC 综合 `m03_synth_3`：184 LUT/394 FF，无 latch/BRAM/DSP/黑盒，0 综合警告/错误。
综合时序有 HD.CLK_SRC/缺少板级 IO delay 的范围限制，不作为实际采样时序通过；详细口径见 M03 文档。
共享综合脚本的 M02 默认路径也重跑通过，421 LUT/250 FF、2 原生开漏 IOBUF，未改变 M02 RTL。
复现、接口、哈希与独立综合证据见 [M03](../doc/m03.md)；下一步 M04 FIFO/AXIS，再 M05 DMA/DDR。

## M04：原生异步 FIFO 与 AXIS

按 steps 连接 M03 的投机字节输出，不下载板卡或建立临时 BRAM/JTAG 快照。
采用已安装 AMD `xpm_fifo_async`：8-bit BRAM 数据 FIFO + 33-bit/16-entry LUTRAM 帧提交 FIFO。
确认整帧后再交给 AXIS；错误/溢出帧按已存长度清理，不输出半帧，也不复位已提交的好帧。
背压、描述符容量保护、下一 SOI 恢复、32/64-bit TKEEP/TLAST/TUSER、统计原子快照已实现。
默认帧上限 65536 字节，未把协议/M03 的 2 MiB 上限标成片上缓存能力。
此前用户 JPG 的 365930 字节 JPEG 帧超限；实际摄像头最大帧长待 M05 测量后选缓存预算。
两个时钟须在 FIFO 初始化/复位恢复期间运行；M05 要协调 PCLK、M02 配置和 DMA 复位。

实际 XSim/XPM 模型的三个配置（32-bit/1024、64-bit/1024、32-bit/65536）分别通过：
1..17 字节尾包、200 组随机长度/异步频率相位抖动、最大长度/多一字节、旧帧错误与新 SOI
同周期、帧外错误、强制背压 FIFO 溢出、描述符饱和、复位中断与全部统计恢复。
各配置还通过真实自有 685-byte JPEG 的 1000 帧 DVP → M03 → FIFO → AXIS 字节记分板，
以每批 25 帧连续发送验证，含 HREF 间隙与真实截断 JPEG 的 VSYNC 撤销。
1..17 字节等接口激励不当作可解码 JPEG；1000 帧仿真不是实际板卡 FPS/稳定性验收。
扩大至 64 KiB 后首次测试因固定 40000 周期排空预算不足而超时，已按深度修正测试预算；
不是修改/放宽硬件丢帧策略，随后三个配置全部通过。
没有新增 Python 包或复制 IP 源码；hook 新增这一个原生检查，详见 [M04](../doc/m04.md)。
完整 hook 已通过：5 份向量一致性与 M00/M01/图片 MVP/M02/M03/M04 共 25 项离线测试。

有效 OOC 综合 `build/vivado/m04_synth_5`（XC7Z020-2，默认 32-bit/64 KiB）：
523 LUT（499 logic/24 memory）、1374 FF、16 BRAM36（11.43%），0 latch/DSP/黑盒。
综合阶段 0 error/critical warning，58 个 warning 保留，包含未使用 IP 输出、内部裁剪与
原生 FIFO FSM 安全状态提示；不宣称零警告。PCLK 13.888 ns / AXIS 10 ns 的综合估计
WNS 4.818 ns、WHS 0.157 ns、WPWS 4.500 ns。
原生约束覆盖的 CDC：PCLK→AXIS 37、AXIS→PCLK 3 个端点均 Safe，Unsafe/Unknown=0；
报告保留无共同主时钟的结构提示与原生宏上下文 waiver，不是物理亚稳态验证。
先加载 EARLY 的 `prj/m04_ooc.xdc`，再处理 XPM scoped 约束；保留原生 max-delay/bus-skew，
不使用全局异步 clock-group 覆盖这些约束。灰码 bus-skew 需求为真实 10 ns，综合估计满足。
早期 synth_2..4 先综合后创建时钟，导致原生约束采用 1000 ns 占位周期，保留作开发记录，
不作最终 CDC 时序产物；synth_1 命令把其他选项放在 -tclargs 后导致参数数量错误，也不计通过。
DCP SHA-256：`79dbece1a1b78863af624f3981b6ac43cda4ce2e47a810d7615f070b0b813c4f`。
综合有 HD.CLK_SRC/无板级 IO delay 的范围限制，bus-skew 未布线；未改板上 M02、
网络或 SD/Flash，未取得实际摄像头 JPEG，M04/G1 物理验收仍待 M05 集成。
下一步 M05：短包发生器 → DMA/DDR → 缓存/错误恢复 → 实拍保存/解码；M11 网络仍最后接入。

## M05：原生 DMA/DDR 集成

新增两个 AMD AXI DMA Simple Mode，capture S2MM 与 crypto MM2S/S2MM，共享 PS HP0；
crypto 本阶段为传输回环，不冒充 AES-GCM。JPEG 双缓冲、独立输出包、64 KiB 上限、
缓存方向、原生 BSP 中断、有界完成/错误/复位处理、所有权与 UART 转储已编写。
主机只读完成且保持 SENDING 的 ELF-owned DDR 帧，再显式 release，没有 BRAM/JTAG 快照旁路。
已有环境完成 Icarus 4 模式/4000 组路由、C 10000 轮所有权、主机边界校验和实际 M05
原生 XSim/XPM 停 PCLK 复位/背压/PCLK witness 检查；M02/M03/M04 回归通过。
M04 桥读侧改用原生异步置低/AXIS 同步释放复位，其三配置各 1000 帧回归再次通过。

开发产物保留但不当验收：m05_board_1 未同步 PS 配置/flush 到 PCLK，CDC/内部时序失败；
首版 XDC 的 foreach 不属于 read_xdc 支持的语法，已展开管脚、分离 EARLY 时钟与仅实现约束。
m05_board_1/2 被本助手停止，产物/日志未删；m05_board_3 完成内部布线时序 WNS 0.449/WHS 0.036 ns，
但复位同步器前还有 CDC-10 组合逻辑提示，已将请求在源域寄存，重新构建 m05_board_4。
旧 Vitis 构建因为期间 RTL 改动被源码哈希保护拒绝，无有效 manifest，没有下载旧版上板。
实际原生 SDT 把 capture 唯一 S2MM 中断放在 IntrId[0]、[1]=ffff，已按配置修正，
不套用双通道示例的 RX 索引；三个 GIC SPI 编码为 401d/401e/401f，使用原生同一套中断封装。

最终 `m05_board_4` 原生实现 WNS +0.464 ns、WHS +0.043 ns，CDC 无 Critical，
10 ns bus-skew 布线无违例，DRC 无 Error；bitstream SHA-256 为
`bf9feae357dbbf17c182b6c4e2155c60b58ed633b819082720e95ad77026a73c`。
同一版 bit/ELF 在 CF7020B 实测缓存关闭的 32 次变长传输及 2 次预期错误后的恢复，
全部 34 次数据/实际长度检查通过，耗时 49166 us；RX IRQ 34、TX IRQ 35、
错误 IRQ 1、预期超时 1、背压计数 211904，最大长度 65536。
结果见 `data/captures/m05_20260927_231856_679327/result.json`。
次日尝试 10000 次时，在下发邮箱命令前发生 ARM AP transaction timeout；
JTAG 能枚举 xc7z020，但 DAP 报 transaction error，故不是 DMA 压测结果。
重上电后旧配置缓存开关各 10000 次通过；实拍被 PCLK 安全检查挡下：
实测 83.9 MHz，超出当前 72 MHz 时钟约束，状态 43，不产生伪图片。
按 OV5640 `0x3035[7:4]` 系统分频定义，将寄存器表从 0x11 改为 0x21，
重建 `m05_pclk42`，保留安全检查，实测 PCLK 41.963 MHz。
新镜像 bit SHA-256 为 `d9f5d82a955e5423975d553142d8f528a5f2fe6b1616c71a29a387b700b4d452`，
布线 WNS +0.464 ns、WHS +0.043 ns，CDC 无 Critical、bus-skew 无违例。
新镜像缓存关闭/开启各 10000 次不同长度传输，加两次预期故障恢复，全部通过；
耗时分别 8437556/2461060 us，无重新下载 bitstream。
32 帧实拍与 1000 帧连续实拍均通过；1000 帧 133750121 us，总长 6277230 bytes，
平均 6277.23 bytes、最大 6331 bytes、约 7.48 fps，零错误/超时/丢帧/溢出。
末帧 `data/captures/m05_20260928_103346_800362/frame.jpg`（6259 bytes）
已按 320×240 JPEG 完整解码并目视确认，之后显式释放 SENDING 缓冲。
M05 和 G1 列出的功能判据已通过；DVP input_delay、M02 20 次物理冷启动及完整 G0 未验收。
复现、接口与容量/IO 验收范围见 [M05](../doc/m05.md)。网络仍最后，不写 SD/Flash。
