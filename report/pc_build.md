# 电脑端构建与离线验证记录

更新：2026-10-06。此记录区分当前工作副本新建的产物、此前的离线/板测证据和本次尚未完成的板卡验收。

**2026-10-07 后续软件交付已更新：** 当前使用 `build/vitis/software_ready_20261007`，已修正 ARM 启动链接配置，有四套固件、匹配
FSBL/`BOOT.BIN`，M04/M05 原生 XSim 已通过。完整自动化入口与本轮结果见
[软件交付记录](software_ready.md)，首次实机以 [bringup](../doc/bringup.md) 为准。
下文保留早期 Vitis IDE/手工构建过程，所述 XSim/FSBL 缺口已由新的 HSI/ARM GCC 路径补齐。

## 环境与目标

- Windows 11；Vivado/Vitis 2026.1 安装在 `E:\fpg\2026.1`，Vivado GUI 显示 bitstream 写入完成。
- 本次 XSA 的器件为 `xc7z020clg400-2`。用户提供的实物照片可读到底板 `ATK-DIY7010/7020P`、核心板 `CF7010B/7020B` 与 `ZYNQ 7020` 标签；摄像头为 `ATK-MC5640 V1.2`，核心板上两颗海力士 DDR 也可见。这与本工程 7020/OV5640 目标一致；上板时仍应通过 JTAG 再确认 IDCODE，照片未直接显示 Zynq 顶部激光料号。
- 新 XSA 来自 `build/vivado/g3_gui/m01.xsa`。Vivado GUI 项目生成了 `m01.bit`、XSA、DRC、时序、利用率与 IP 状态报告；`.xsa` 内的 `sysdef.xml` 器件字段也为 `xc7z020clg400-2`。时序报告 WNS=+0.013 ns、WHS=+0.018 ns，且报告称用户约束满足；DRC 仍有 warning/advisory，其中 `PLCK-12` 指出 OV5640 PCLK 在 W14 使用非专用时钟路由，并由 `CLOCK_DEDICATED_ROUTE FALSE` 允许继续实现。此警告仍需按板级时钟质量评估，不能称为零警告构建。

## 本次生成的电脑端产物

- 从该 XSA 为 `ps7_cortexa9_0` 生成 Standalone BSP；Vitis 2026.1 ARM GCC 13.4.0 在 `-mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard` 配置下编译了 BSP 驱动对象并生成 `libxil.a`，BSP make 返回 0。
- 使用 `-O3 -Werror` 编译 G3 C 应用时，修正了 UART 查找调用把基地址误作设备 ID 的问题；应用对象编译通过，并链接成 ARM ELF。
- ELF 核对为 ELF32 little-endian ARM。`g3_job`、`g3_frame`、`g3_sealed` 分别为 128、65600、68096 字节，均按 64 字节对齐，地址落在 0x00100000–0x40000000 的 DDR 范围内。
- 本机可运行目录为 `build/vitis/g3_delivery`，其中包含 `build_manifest.json`、ELF、与 XSA 同源的 bitstream 和 `ps7_init.tcl`。该目录在 Git 忽略的 `build/` 下，不作为源码提交；清单会校验 XSA、工程源码和交付二进制的 SHA-256。
- Vitis Python 客户端/IDE 自动化在此受限运行环境启动不完整，因此本次 G3 ELF 采用已生成 BSP、Vitis ARM 编译器和对应 Zynq-7000 DDR linker script 完成。不要把此手动链接路径描述成 Vitis GUI 中完整应用组件流程已通过。

## 本次验证结果

- G3 主机协议检查：`python sim/tb/test_g3.py` 通过。
- `git diff --check` 通过。
- G3 ELF 结构、DDR 符号大小/边界、构建清单和 XSA 器件字段已核对。
- 本轮复跑：M00（10 项）、M09（ACVP 25/25/10 组与 1000 次）、M10、M12（2 项）、G3 主机检查、G5，以及 M08 AXI-GCM（102 组、背压/异常/零化）均通过。提交钩子的四项 M00/M10/M12/G5 全通过。C 编译器使用 Vivado 附带的 MinGW GCC 9.5.0。
- 2026-10-06 使用当前 MSYS2 Icarus 13.0 复跑：AES MVP（3 项）、M01（5 项）、M02（4 项）、M03（2 项）、M07（1 项）和 M08（102 个 AES-GCM 向量/背压/异常/零化）均通过；M05 帧所有权/边界、AXIS 路由和 DMA 缓冲区 3 项中 2 项通过，原生 XSim 集成仍失败。部分 Icarus 编译器以 Windows 状态 `3221225477`（访问冲突）退出，但已生成非空 VVP 文件；共享严格兜底仅在此精确退出码且产物非空时继续，随后仍须由 `vvp` 实际运行并匹配功能标记。M01 心跳、M02 SCCB/OV5640、M03 1000 帧采集与错误恢复、M07 GHASH、M08 端到端 AES-GCM，以及 M05 两个局部项均有通过输出。复现使用 `VIVADO_ROOT=E:\\fpg\\2026.1\\Vivado` 并把 `C:\\msys64\\ucrt64\\bin` 加入 `PATH`。
- 故障定位：Vivado 2026.1 的 `xelab -v 2` 显示它选择 `E:\\fpg\\2026.1\\Vivado\\tps\\mingw\\6.2.0\\...\\gcc.exe`；直接启动内置 GCC 6.2.0 和 8.3.0 均报 Windows“无效的系统 DLL 重定位”，而 GCC 10.0.0 能单独编译该生成的 C 文件，但没有完成 XSim 快照链接。AMD 2026.1 文档说明可由 `launch_simulation -gcc_install_path` 指定编译器；本次批处理探针在 Vivado 工程初始化时遇到 `Common 17-354 Could not open 'C' for writing` 并异常终止，因此 GCC 覆盖流程还没有通过验证。以上均不改变 M04/M05 当前失败状态，旧的 XSim/XPM 与板测记录仅作为历史独立证据。

## 仍需板卡验证

- 本轮系统设备列表没有检出 JTAG/USB 下载器，且本机 3121 端口没有运行 `hw_server`；没有执行 JTAG 下载，也没有重新连接 OV5640 做端到端采集/加密。因此 `build_manifest.json` 的 `board_validated` 保持 `false`。硬件照片已确认 7020 标签、`CF7010B/7020B` 核心板和 `ATK-MC5640 V1.2` 摄像头；首次下载前仍须通过 JTAG 核对 IDCODE。
- 当前 G3 目录尚无 `BOOT.BIN`/FSBL。已尝试从 G3 XSA 创建 Vitis 2026.1 Standalone 平台并构建 Zynq FSBL；服务启动后平台生成失败，返回 `Error in generating Processor List`，未生成可用 FSBL。未使用其他 XSA 的 FSBL 拼装启动镜像，也未写入 SD/Flash。若提交要求 SD 冷启动，需要先修复 Vitis Processor List/Lopper 生成环境，再用本 XSA 重建并实测。
- 首次 G3 板测需要摄像头接 P2、板卡 JTAG USB 接电脑，并运行 Vivado `hw_server`。在仓库根目录执行：

  ```powershell
  & 'E:/fpg/2026.1/Vivado/bin/hw_server.bat'
  # 另一个终端；首次测试会临时下载 PL bitstream 和 PS ELF，不写 SD/Flash。
  & ./.venv/Scripts/python.exe src/host/g3_board.py build/vitis/g3_delivery --boot --count 1 --tool-root E:/fpg/2026.1
  ```

- 完整比赛/整机验收仍需按 [G3](../doc/g3.md)、[进度表](progress.md) 中的未完成项逐项复现；历史板测记录不等于本次新建产物已经上板通过。
