# 开发板子项目

负责领航者 CF7020B（XC7Z020）的 PL/PS 实现及构建调试。板端继续使用 Vitis Standalone + USB0 Slave，
采集 OV5640 JPEG、完成 ML-KEM Decaps 和 AES-GCM 加密，将密文交给 PC 转发。
目标架构见 [三端架构](../doc/architecture.md)，共享协议见 [protocol](../doc/protocol.md)。

2026-10-15握手恢复修复：普通G6也使用发送失败时DTR/epoch证据区分正常断连，安全清理旧会话后才接受新握手；
真实致命错误清除身份后保持FAULT，开发态同样不能被断连路径改回WAIT_HELLO。
当前易失实测构建为 `build/vitis/g6_handshake_recovery_20261015_1`，75项哈希/BSP/ARM预检通过，
JTAG开发态已加载；SD/Flash不改。强制关闭客户端与低带宽后重连记录见 [修复报告](../report/handshake_recovery_20261015.md)。

| 目录 | 内容 |
|---|---|
| `src/rtl/` | 摄像头、异步 FIFO、AXIS、AES-GCM 与独立 Keccak 实验 |
| `src/ps/` | 裸机固件、协议、会话、DMA/USB 驱动适配与诊断 |
| `src/third_party/` | 固定版本 ML-KEM / 哈希库及许可证；PC 黄金参考也复用这些源码 |
| `prj/` | Vivado/Vitis、JTAG、构建预检、板测和交付辅助脚本 |
| `xdc/` | 板级引脚与时序约束 |
| `vendor/`、`output/` | 本地官方资料和生成/测试材料，Git 忽略 |

从仓库根目录执行：

```powershell
& ./sim/scripts/run_m01.ps1
& ./board/prj/check_environment.ps1 -ToolRoot 'D:/AmdDesignTools/2026.1'
# 构建不等于上板验收，使用新的输出名称：
& ./board/prj/build_m01.ps1 -ToolRoot 'D:/AmdDesignTools/2026.1' -BuildName m01_layout
```

迁移前 `build/` 中的 manifest 与工程包含旧路径，需按新目录重新构建和预检。
板测、生产安全、G0/G7 状态以 [最新进度](../report/progress.md) 为准；以下为早期硬件资料研究，
其中设备枚举描述只代表记录当时，不代表当前连接状态。

## 三端 MVP 固件与准备入口

本轮按新目录构建 `build/vitis/g6_mobile_bridge_20261012_1`，开发态 G6 ELF 与 73 项清单预检通过。
复用历史 `build/vivado/g4_usb_1/m01.xsa`，其内置 bit 与本机历史 G6 所用 bit 相同；未重新实现 PL，未上板。
新软件采用 `development_jtag_mailbox_secure_cleanup`，不代表 production provider/熵源已完成。

```powershell
# 在新输出目录重新构建软件；输入 XSA 需来自匹配的完整硬件工程。
& ./.venv/Scripts/python.exe board/prj/build_software.py --xsa build/vivado/g4_usb_1/m01.xsa --output build/vitis/g6_mobile_bridge_new --tool-root D:/AmdDesignTools/2026.1 --apps g6_usb --g6-dev-secure-cleanup
# 默认仅检查固件并导出公开身份，不访问 JTAG/CDC；必须使用新的导出目录。
& ./.venv/Scripts/python.exe board/prj/prepare_mobile.py --workspace build/vitis/g6_mobile_bridge_20261012_1 --identity-output board/output/mobile_identity_new
# 板卡连接时加 --provision：临时 JTAG boot/provision，不发 HELLO/START、不打开视频口。
# 手机只接收导出目录里的 public.bin 与独立核对的 public.sha256，绝不复制 board/output/m09/private.bin。
```

准备入口保留固件哈希、开发态私钥与公钥一致性检查，退出时覆盖本次拥有的私钥缓冲。
PC 经 JTAG 装载测试私钥仍属于可信开发环境；准备与公开身份导出不能算认证视频已通过。
板端 6 项无硬件 mock 测试通过，完整链路步骤见 [三端 MVP](../doc/three_end_mvp.md)。

## 公网透明中转接口（2026-10-14）

四端路线见 [公网中转契约](../doc/cloud_relay_plan.md)：Board ⇄ USB ⇄ PC WSS ⇄ OpenSSH 反向 TCP 隧道 ⇄ Android。
云端只转发 TCP；TLS、账号和 USB owner/队列仍由 PC 管理，suite2 的身份 bootstrap、临时 KEM、
双向 Finished、START/STOP/REKEY 与认证视频记录不变，板端无需新增云端地址、网络栈或密码核。

控制 body 最大 1024 字节，临时 offer/reply 完整控制记录为 876/844 字节，USB 外层仍为 channel + BE16 长度。
板端握手 15 秒及业务 1800 秒硬截止保持，客户端于 1785 秒提前重建；公网延迟或背压超限时按既有失败/清理规则停流。
开发态 PC 已知 JTAG seed，不能声称对恶意 PC 前向保密；G6 视频 SD 自主启动仍未完成。
公网 G9 不替代 G0/G7/G8。本轮仅接口审查和离线回归，详见 [板端云中转报告](../report/board_cloud_20261014.md)。

## M01 硬件资料

官方硬件资料目录需由使用者自行提供；例程源码位于该目录的 `4_Source_Code` 子目录，包含
`1_FPGA_Design/ZYNQ_7020_FPGA.rar`、`2_Embedded_Vitis/ZYNQ_Vitis_7020.rar`。
已按需解压 FPGA LED/OV5640 和 Vitis UART/Timer/lwIP/JPEG 等 8 个工程，
核对 XPR/BD：Vivado 2020.2，器件 `xc7z020clg400-2`。
来源 SHA-256、摄像头引脚、PS 参数、完整数据链路和问题见 [官方例程研究](../report/vendor_examples.md)。

原始源码位于本地 `board/vendor/`（Git 忽略），清单保存在 `board/vendor/manifest.json`。
导入脚本为 `board/prj/import_vendor.ps1`；仅在空目录使用，现有文件不会被覆盖。
用户提供的实物照片可读到底板 `ATK-DIY7010/7020P`、核心板 `CF7010B/7020B`，并有 `ZYNQ 7020` 标签；摄像头模组标记为 `ATK-MC5640 V1.2`。照片未显示 Zynq 芯片顶面完整激光料号，首次下载前仍以 JTAG IDCODE 和核心板修订资料核对 `xc7z020clg400-2`。当前设备枚举未发现 JTAG 下载器，因此新 G3 镜像尚未在这块实物上验证。
特别注意：hello/echo 等工程配置 DDR3L `MT41K256M16`，摄像头工程配置 DDR3 `MT41J256M16`；
未核对核心板丝印/供电前不能混用这两套 DDR 参数。

用户已确认实物为两颗 SK hynix `H5TC4G63EFR-RDA`，合计 1 GiB、32-bit。
已核对新增核心板 V2.5 原理图：DDR 1.35 V、UART0 MIO14/15、GEM0 MIO16..27、
MDIO MIO52/53、SD0 MIO40..45 与 M01 一致；按海力士数据手册设置 Custom CL8/CWL6。
原理图中的内存为 NT5CC256M16、PS PHY 为 YT8521SC-CA；实物 MDIO 已读到
YT8521 ID `0000:011A` / 地址 7。AMD lwIP 与旧官方 echo BSP 无该分支，现已在
新生成 BSP 中加入最小适配，不改原始例程或安装目录；实际收发尚未验证。
原理图、走线 CSV 的路径和 SHA-256 见研究记录第 7 节。

官方入口来自 [正点原子 Products 仓库](https://github.com/alientek-openedv/Products)，
已核对提交 `d917adac269f72ea1fb008baaed4d25319fcdf0c`：

| 板型 | 官方资料索引 | 资料盘 | 提取码 |
|---|---|---|---|
| 领航者 V1 | [zdyz_linhanz.rst](https://github.com/alientek-openedv/Products/blob/d917adac269f72ea1fb008baaed4d25319fcdf0c/zdyz_docs/boards/fpga/zdyz_linhanz.rst) | [A盘](https://pan.baidu.com/s/1JmK44KIMsIImjxBQ4qKvCQ) | krg1 |
| 领航者 V2 | [zdyz_linhanz(V2).rst](https://github.com/alientek-openedv/Products/blob/d917adac269f72ea1fb008baaed4d25319fcdf0c/zdyz_docs/boards/fpga/zdyz_linhanz%28V2%29.rst) | [A盘](https://pan.baidu.com/s/1vXxmhg_mZm_OVg4xQeiCVQ) | zdyz |

必须从所选版本提取并互相核对：

- 器件完整 part、封装、速度等级，以及底板和核心板原理图。
- P2 摄像头接口 XDC、Bank IO 电压、摄像头时钟/复位、SCCB 与 DVP 极性。
- OV5640 例程的 SCCB 和 JPEG 初始化表；RGB 例程不能直接视作 JPEG 配置。
- PS DDR、UART、PS GEM、MIO、时钟、复位和中断配置（BD/PS preset/Tcl）。
- 官方工程的 Vivado 版本及迁移到本机版本后的 IP 升级报告。

2026-09-26 本机找到 Vivado 2026.1 安装，`-version` 报告 v2026.1，
SW Build 6511674、IP Build 6504888、SharedData Build 6501428。
这是本机版本；已解压的 XPR/BD 为 2020.2。实际创建工程时许可证有效，
最初器件库缺少 Zynq-7000；2026-09-27 用户补装后，`get_parts xc7z020clg400-2`
已找到器件，新的海力士配置工程实际完成综合/实现/bitstream/XSA/ELF。
官方旧 Tcl 有 2020.2 版本守卫，camera BD 的 Video In 4.0 在本机为 5.0；不能直接照搬生成结果。

本机 `xsct.bat` 明确报错“XSCT is disabled in Vitis 2026.1 release”。
M01 使用 Vitis Python 接口建立 Standalone 平台与应用，
参考 [AMD UG1400 2026.1 XSCT 迁移说明](https://docs.amd.com/r/en-US/ug1400-vitis-embedded/XSCT-to-Python-API-Migration)。
CLI 示例位于安装目录的 `Vitis/cli/examples`；不使用旧 XSCT 项目脚本。

运行环境预检（返回 2 表示工具或官方资料待补齐）：

```powershell
& ./board/prj/check_environment.ps1 -ToolRoot 'D:/AmdDesignTools/2026.1'
```

预检只列出工具、候选资料和串口，不下载固件、不改写板卡，也不能替代 G0 上板测试。
M01 已提供独立 Tcl BD、LED 心跳、Standalone 自检、lwIP echo 与主机探针，
见 [构建和上板说明](../doc/m01.md)。新硬件/软件及 SD0/FSBL 离线构建已通过。
JTAG 已临时下载，COM4 的 CH340 已采集到 UART 启动、DDR scratch 及定时器正常日志。
V3.9 底板 P5 的 1–3、2–4 对应 PS 串口。当前 PHY link=0；按用户调整，网络配置/验收后置。
LED 和 30 分钟冷启动判据保留，独立 M02 编写/仿真不被未接网口阻塞；见 [M02](../doc/m02.md)。
