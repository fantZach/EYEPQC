# 执行线 B：G0 与交付证据整理

更新：2026-10-09。范围为 G0 构建/验收工具审阅、现有证据离线复核，以及统一验收矩阵与现场流程。未访问 UART、JTAG、USB 或板卡，未写 SD/Flash。

## 离线审阅结果

- final2 镜像预检通过：build ID `9654837c3428`，BOOT.BIN SHA-256 `4c2760e609024f329f3f9d0c4aeb6d84c9de70872ce900e89d9d562a33410386`。manifest 同时校验 XSA、BSP、ELF/FSBL、源输入、实现后 LED/时钟报告及构建产物哈希；`board_validated=false`。
- 既有 JTAG 日志按当前 manifest 离线重验通过：单次启动、BOOT_MODE `0x00`、3 个 STAT 样本、末次 uptime 30 秒、DDR PASS 计数 2；此结果只适用于临时 JTAG/局部 scratch 与 timer/LED 探测，不是 SD 或冷启动验收。
- `py_compile` 覆盖 G0 acceptance、软件构建、source manifest 和对应测试；`sim.tb.test_g0_acceptance` 7/7 通过；G0 构建入口与 JTAG wrapper 的 PowerShell AST 解析通过。
- source-manifest 当前快照保存于忽略目录 `build/parallel_20261009/B/g0_sources.json`。G0 脚本未发现需本轮修复的离线缺陷：输出目录要求唯一，板测入口默认 dry-run，UART 采集显式指定端口且以独占新文件保存原始日志。

本轮没有重新跑 Vivado/Vitis 完整构建；既有可复现产物通过了 manifest 预检。尚缺 SD 介质准备条件，因此不执行 SD 启动或任何板测。完整逐项判据见 [验收矩阵](acceptance_matrix_20261009.md)。

## 交叉审阅与脱敏 Benchmark

- 脱敏汇总脚本只读取固定路径 allowlist；单元测试通过临时 JSON fixture 调用同一提取代码，不依赖 Git 忽略的 captures/build，也不会伪装真实数据。失败的单轮 G7 保持失败；两个 G3 窗口分别保留帧数/FPS，不跨轮求和或外推。缺失指标与未读回板端计数维持 `null`。G3 历史源没有 `status` 字段，摘要明确标为未记录，并依据源中既定 board 标记和计数判据分类；显式 failed/error 不会通过。当前 12/12 单测通过；本机 10 条证据汇总通过，含 C route4k 离线构建记录。复现命令及字段定义见 [Benchmark 说明](benchmark_summary_20261009.md)。
- C route4k 核验清单位于 `build/parallel_20261009/C/route4k/build_manifest.json`。逐项重算源输入和输出产物哈希均与 manifest 一致；XSA SHA-256 `70fe149c62b3a2cc402adfb78fac625520151309015d89815576784a1fd250a2`，BIT SHA-256 `261b8f7dde47ed153f798bc2fc9eecf78570bfc23dde77596c75d644152f407a`。HWH 映射为 `0x43C10000–0x43C10FFF`，与 M01 AES `0x43C00000–0x43C00FFF` 不重叠；目标 `xc7z020clg400-2`。PS 配置与 M01 的 49 个非 GP0 参数一致，GP0 按 AXI 需要启用。已布线 WNS `+0.306 ns`、WHS `+0.074 ns`，DRC 检查 0；资源为 6731 LUT、7104 FF、0 BRAM、0 DSP。此证据仅为离线实现/XSA，没有板级 MMIO 或性能测量。
- 只读审阅 A 的 Chapter 9 修复时，对照了真实 `usbps_v2_11` SETUP 路径：SDK 在 SETUP 回调前不清空/退休 EP0 IN dTD，TX completion retirement 在回调之后。candidate005 的标准请求安全门槛和局部 cleanup/reinit 已通过 host 3/3、G6 recovery 9/9、离线构建；但 candidate005 未上板。随后审查发现 `prj/usb_probe.c` class SETUP 绕过 `StdDevReq` gate：`GET_LINE_CODING` 将静态 `line_coding` 交给 EP0 IN dTD，之后 `SET_LINE_CODING` 的 DATA_RX 可能在旧 IN dTD quiesce 前 `memcpy` 同一 buffer。candidate004 USB 枚举失败仍保留；用户拔插后旧 usbfix3 基线恢复 COM16/认证视频，不推断原因。candidate006 正在把 ownership gate 前移至所有 SETUP dispatch，并为 class EP0 send/status 与 line_pending 时序添加覆盖；完成前不安排板测或宣称 G7 通过。

## 现场流程与回滚

**本轮不执行以下步骤。** 用户本轮确认没有读卡器，板上有一张 SD 卡并保持原样、不写入。只有后续具备读卡器和可写入的专用 SD 卡，并确认对应板卡版本手册后，才进入 SD 现场门禁。不得用旧卡内容、JTAG 加载或 BOOT_MODE 单项读数代替 SD 冷启动证据。

1. 在电脑上复核 `build/vitis/g0_20261008b_startup_final2/g0_manifest.json`，并核对 BOOT.BIN SHA-256 与本报告一致。将该镜像仅写入专用 SD 卡根目录；保留原卡/原镜像，不覆盖原始证据。若无法确认专用卡或写入方式，停止在此步骤。
2. 按 CF7020B 对应硬件版本手册核实 SD 启动跳帽/拨码。将 UART 采集端接到已核实的 PS UART，先启动被动采集，明确写出实际 COM 号；不自动枚举猜测端口，也不并行启动 G6/G7 接收器。
3. 在独占板卡窗口按采集器提示完成全断电再上电。观察并记录 H15 LED；不经 JTAG/USB 辅助启动。确认日志中的 build ID 为 `9654837c3428`、BOOT_MODE 为 `0x05`、DDR/TIMER/READY 均出现后，保持运行 30 分钟。若启动标记、镜像 ID、LED、串口连续性或错误计数不符，保留当前日志并停止，不重试覆盖。
4. 正常结束后，保留 JSONL 原始串口记录及相邻 `.result.json`；离线运行：

   ```powershell
   .\.venv\Scripts\python.exe prj/g0_acceptance.py verify --manifest build/vitis/g0_20261008b_startup_final2/g0_manifest.json --log <本次唯一JSONL路径> --scenario sd_cold_start_30m --minimum-seconds 1800
   ```

   验收需单次 SD BOOT、无重启/错误、30 分钟定时器与周期 DDR 计数连续、人工 LED/介质/跳帽/全断电确认完整。串口断线、失败标记、额外 BOOT 或任何错误均判该次失败。
5. 物理复位是单独门禁：复用同一启动镜像和被动 UART，使用唯一新日志运行 `reset_probe`；READY 后按板卡手册确认的复位键恰好一次，要求恰好两次 SD BOOT 且第二次出现 DDR/TIMER/READY/STAT。该门禁通过后不要据此声称 30 分钟冷启动通过。

失败回滚只恢复本次改变的 SD 卡文件/启动拨码到操作前记录状态；不要触碰 JTAG、USB 或其它 G6 基线，不重写覆盖失败 JSONL。若卡或板卡状态无法确定，停止并保存原状与日志，交由唯一板卡拥有者 A 决定后续处理。

## 本轮可给主线的交付建议

- B 线报告、验收矩阵和现场流程已交付；正式 README、progress、下一阶段计划与提交检查表已按主代理授权统一整合，待审核后再做 Git 操作。
- 已新增脱敏 allowlist 汇总器与 10 条隔离记录：[Benchmark JSON](benchmark_summary_20261009.json)、[字段说明](benchmark_summary_20261009.md)。脚本及 12 项 fixture 测试分别为 `prj/collect_benchmark_summary.py`、`sim/tb/test_benchmark_summary.py`。记录按构建和场景独立保存，未记录的分辨率、字节数、错误数和板端计数保持 `null`；电脑端 build/preflight 明确标为 offline。尚未覆盖的是缺少结构化原始 JSON 的 G4/G5 历史结果和统一延迟/资源指标。已有 15 秒录像为 722/722 帧，不能外推为长录；约 50 分钟记录按用户时长例外，不写成实测 2 小时。
- 公开提交只引用脱敏摘要和复现步骤。JTAG 私钥/seed、原始 UART/capture、build/Vivado/Vitis 产物和 `g7_runs` 不进入公开报告或 Git；本地路径用于追溯。无需因此生成尚未指定格式的论文、PPT 或竞赛包装文件。
