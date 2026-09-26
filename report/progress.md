# Implementation progress

更新：2026-09-27。实施依据 `doc/steps.md`，采用 Ponytail：复用密码库与标准库，
以能运行、能比对的最小链路推进，保留必需的长度检查和认证边界。

## 当前状态

| 步骤 | 状态 | 产物/证据 |
|---|---|---|
| 立即清单 1：目录与忽略规则 | 完成 | src/rtl、src/ps、src/host、sim、data、board、report、skill；build 生成目录已创建并忽略 |
| 立即清单 2：官方资料与工具 | 源码研究完成，实物待确认 | 已提取 8 个官方工程并记录压缩包 SHA-256；XPR/BD 为 2020.2、xc7z020clg400-2；发现 DDR3/DDR3L 配置差异 |
| M00：协议与黄金参考 | 完成（主机离线验证） | C/Python 协议实现、标准/随机/篡改向量、独立 GHASH 中间值和复现脚本 |
| M01 / G0 | 已核对源码、未通过 | 摄像头 XDC、DDR/UART/GEM/FCLK/IRQ 已记录；实物 DDR/版本待确认；未检测到串口；未创建新 BD/bitstream/Standalone 应用 |
| M02～M15 / G1～G7 | 未开始 | 按步骤继续，当前不越过板级门禁；ML-KEM PL 优化等 G0～G7 通过后进行 |

板级资料已解压并完成源码研究；继续上板前必须核对实物 DDR/板卡版本并完成工程迁移。
已有 `doc/steps.md` 是用户的未跟踪文件，未改写；没有提交 Git 或覆盖原有文档。

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

## 下一步：M01

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
本次提交前 hook 再次通过，M00 10 项测试通过；未创建 Git 提交。

下一步：核对实物 DDR/版本 → 基于 hello/echo PS 配置重建最小 BD → 导出 XSA →
Vitis Python 接口建立 Standalone/UART/DDR/lwIP echo → 实际板卡验证 30 分钟 → 进入 M02。
本机 Vitis 2026.1 禁用 XSCT，后续构建使用 Python API。
板级 pin/DDR/IO 参数未确认前，不能声称 bitstream 可用或通过 G0；需留存实际上板日志和测量结果。

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
hook 校验工作区文件，不自动暂存、生成向量或创建 Git 提交；尚未提交当前代码。
