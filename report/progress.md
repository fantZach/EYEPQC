# Implementation progress

更新：2026-09-27。实施依据 `doc/steps.md`，采用 Ponytail：复用密码库与标准库，
以能运行、能比对的最小链路推进，保留必需的长度检查和认证边界。

## 当前状态

| 步骤 | 状态 | 产物/证据 |
|---|---|---|
| 立即清单 1：目录与忽略规则 | 完成 | src/rtl、src/ps、src/host、sim、data、board、report、skill；build 生成目录已创建并忽略 |
| 立即清单 2：官方资料与工具 | 源码研究完成，实物待确认 | 已提取 8 个官方工程并记录压缩包 SHA-256；XPR/BD 为 2020.2、xc7z020clg400-2；发现 DDR3/DDR3L 配置差异 |
| M00：协议与黄金参考 | 完成（主机离线验证） | C/Python 协议实现、标准/随机/篡改向量、独立 GHASH 中间值和复现脚本 |
| M01 / G0 | 部分上板通过、门禁未通过 | 新硬件/SD0/FSBL 构建通过；CF7020B / COM4 JTAG 验证 UART、DDR scratch、定时器；YT8521 ID 已确认并适配；M01 4 项、M00 10 项及 hook 通过；link=0，网络/LED/冷启动待验收 |
| M02～M15 / G1～G7 | 未开始 | 按步骤继续，当前不越过板级门禁；ML-KEM PL 优化等 G0～G7 通过后进行 |

板级资料已解压并完成源码研究；用户已提供 DDR 型号/颗数，新增原理图已核对。
已临时 JTAG 下载并采集 COM4；需要确认 PS 网口接线/网络地址，继续网络和冷启动验收。
M00 与官方研究已提交为 `e649634`；M01 代码和上板记录随本次里程碑提交，
不包含官方例程或生成产物。没有改写 `doc/steps.md`。

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

原始官方源码未改写；没有向实物板卡下载；当前仍没有可见串口。
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

下一步：确认 PS 网口接线/地址 → 实际 ping/echo、LED 验证 →
基于同平台 SD 冷启动运行 30 分钟 → 确认 G0 后进入 M02。
已易失性 JTAG 下载；未写 SD/Flash。用户确认 PS 网口未连接，协商超时符合当前接线状态。
最终软件为 `m01_cf7020b_v2`，原始日志/输出哈希见 M01 文档。

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
M01 新增后顺序为暂存空白检查、向量一致性、M00 10 项、M01 4 项离线测试。
hook 校验工作区文件，不自动暂存、生成向量或创建 Git 提交；本次按用户要求暂存并提交 M01。
