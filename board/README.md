# Board inputs for M01

已找到用户提供的官方例程目录 `D:/BaiduNetdiskDownload/4_Source_Code`，包含
`1_FPGA_Design/ZYNQ_7020_FPGA.rar`、`2_Embedded_Vitis/ZYNQ_Vitis_7020.rar`。
已按需解压 FPGA LED/OV5640 和 Vitis UART/Timer/lwIP/JPEG 等 8 个工程，
核对 XPR/BD：Vivado 2020.2，器件 `xc7z020clg400-2`。
来源 SHA-256、摄像头引脚、PS 参数、完整数据链路和问题见 [官方例程研究](../report/vendor_examples.md)。

原始源码位于本地 `board/vendor/`（Git 忽略），清单保存在 `board/vendor/manifest.json`。
导入脚本为 `prj/import_vendor.ps1`；仅在空目录使用，现有文件不会被覆盖。
实物底板、7020 核心板和摄像头模组版本仍需确认，源码不能替代实物核对。
特别注意：hello/echo 等工程配置 DDR3L `MT41K256M16`，摄像头工程配置 DDR3 `MT41J256M16`；
未核对核心板丝印/供电前不能混用这两套 DDR 参数。

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

2026-09-26 本机找到 `D:/AmdDesignTools/2026.1`，Vivado `-version` 报告 v2026.1，
SW Build 6511674、IP Build 6504888、SharedData Build 6501428。
这是本机版本；已解压的 XPR/BD 为 2020.2。设备支持与许可证需在创建实际工程时检查。
官方旧 Tcl 有 2020.2 版本守卫，camera BD 的 Video In 4.0 在本机为 5.0；不能直接照搬生成结果。

本机 `xsct.bat` 明确报错“XSCT is disabled in Vitis 2026.1 release”。
M01 使用 Vitis Python 接口建立 Standalone 平台与应用，
参考 [AMD UG1400 2026.1 XSCT 迁移说明](https://docs.amd.com/r/en-US/ug1400-vitis-embedded/XSCT-to-Python-API-Migration)。
CLI 示例位于安装目录的 `Vitis/cli/examples`；不使用旧 XSCT 项目脚本。

运行环境预检（返回 2 表示工具或官方资料待补齐）：

```powershell
& ./prj/check_environment.ps1 -ToolRoot 'D:/AmdDesignTools/2026.1'
```

预检只列出工具、候选资料和串口，不下载固件、不改写板卡，也不能替代 G0 上板测试。
下一步基于 hello/echo 的待确认 PS 基线创建最小 BD，生成 XSA，再编译 UART/DDR/lwIP echo。
之后记录 LED、UART、DDR、ping/echo 和 30 分钟冷启动运行结果；通过 M01 后进入 M02。
