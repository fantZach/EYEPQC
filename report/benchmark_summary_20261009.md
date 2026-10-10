# Benchmark 汇总字段与复现说明

本汇总由 [`prj/collect_benchmark_summary.py`](../prj/collect_benchmark_summary.py) 从少量明确列出的既有 JSON 证据生成。输出为 [`benchmark_summary_20261009.json`](benchmark_summary_20261009.json)。来源路径固定在脚本 allowlist 中；不会 glob“最新”目录，也不会自动把新失败/通过批次并进来。C route4k 离线实现已按 manifest 和源/产物哈希加入；006d 最终板测已另建固定来源独立审核摘要，见下文；本脚本的 10 条历史记录保持其原始范围。脚本不打开 JPEG/录像载荷；仅抽取 allowlist 内的构建身份、场景、时间、帧/字节/计数器字段，并将输入文件的 SHA-256 与仓库相对路径写入来源列表。

## 字段

- `record_id`：唯一运行记录 ID；每个 build、故障场景和测试窗口各占一条记录，不跨运行合并。
- `scenario`、`evidence_class`、`outcome`：场景名、证据类型和该行结果。`offline_build`、`offline_artifact_check` 明确表示电脑端产物检查，不能当作板测。
- `build`：已被来源明确记录的 `variant`、`build_id`、manifest/ELF/bit/XSA SHA-256；来源没有的项为 `null`。
- `time_window_s`、`frames`、`fps`、`bytes`、`resolution.width/height`：测量窗口、帧数、帧率、字节数与分辨率。没有单项直接证据时保持 `null`。故障恢复延迟单独位于 `details.recovery_latency_us`，不会冒充整段视频时长。
- `error_counts`、`board_counters`：来源明示的错误/板端计数。若没有板端读回，`board_counters` 为 `null`；不会把缺失值补成 0。G3 的 dropped/overflow 仅在源 JSON 明确记录时列出。
- `details`：不参与跨场景合并的补充字段，例如 G0 boot mode、G7 故障前后帧数或录像 callback 数。
- `sources`：仓库相对路径与原始证据文件 SHA-256。构建 ID、FPS、计数器和来源行留在同一个 record 内。

## 当前数据边界

当前 10 条记录另含 C route4k Keccak PS AXI-Lite 的离线实现/XSA，源和产物哈希均已验证；地址范围 `0x43C10000–0x43C10FFF`，板级验证为 false，帧/FPS/字节均为 `null`。其余记录包括 G0 final2 离线 manifest 预检与 30 秒临时 JTAG 探测，G3 两次独立快速实测，G6 一次 3 秒开发态 USB 会话，15 秒实机录像的全段统计，以及 camera-reset candidate7、routing-stall candidate6 各一条独立单轮记录。候选构建不合并；G3 原 JSON 未记录分辨率，结果中保持 `null`；两条 G3 历史源也未记录 `status`，摘要显式标记 `source_status_recorded=false`，仅按源中既定 `board_validated` 与运行计数判据分类；若来源显式记录 `failed`/`error`，则不会判为通过。录像全段 FPS 包含换钥暂停，录制回调帧数 722/722；未记录录像字节数则保留 `null`。G6 的 `board_counters` 原字段为 `null`，汇总仍为 `null`。

该 JSON 是可审阅的已知证据摘要，不表示 G0、G7 或生产安全整体验收完成。约 50 分钟长测的时长例外不是 2 小时实测；G4/G5 文档历史值和没有结构化原始数据的 20 轮批次不伪装成统一 Benchmark 行。离线 candidate build 仅作为离线构建记录，所有性能字段均为 `null`。

## 006d 最终批次的独立摘要（2026-10-10）

[006d 验收 JSON](g7_candidate006d_acceptance_20261010.json) 和 [报告](g7_candidate006d_acceptance_20261010.md) 记录 camera-reset 20/20、routing-stall 20/20 及一次短时基线。独立脚本 `prj/summarize_g7_candidate006d.py` 固定精确终态目录并核验 180 项 manifest 哈希、逐轮构建身份、认证帧、session/key novelty、软件 deadline、计数器和 JTAG 加载范围。输出不含 session ID 或 key fingerprint。现有 Benchmark JSON 仍为 10 条历史记录，不把 40 轮合入旧的不同构建单轮数据。

同构建 PC 退出/DTR 与物理 USB 20 次尚未通过。以下模板保留设计说明；已封存的这两组由上述独立入口复现，不需要改动旧汇总的 allowlist。

## G7 同构建批次记录模板

[`benchmark_g7_recovery_template_20261009.json`](benchmark_g7_recovery_template_20261009.json) 定义 candidate-v4 的脱敏批次字段。正式摘要只在 A 封存终态目录并给出最终报告后，才将精确批次路径加入脚本 allowlist。每个批次按 camera-reset、routing-stall 等场景独立记录；每轮保留成功、失败、超时或不完整状态，不把处理中批次写为通过。所有 trial 必须匹配同一 allowlist manifest、ELF、XSA 哈希。模板只导出 session/key 是否变化及唯一性计数，不导出 session ID 或 key fingerprint；帧数仅表示故障前与恢复后的认证帧，不外推为整轮 FPS。S2MM Busy 到软件 deadline、受控 PL camera reset、受控 PL routing stall 分字段分类，不以硬件 timeout IRQ 作为门槛。

在批次封存前，`report/g7_runs` 中的运行目录是可变输入，不加入公开摘要。最终审核还需逐轮核实新旧 session/key novelty、约 3 秒 software deadline、恢复 HELLO 与认证帧计数、计数器差值、JTAG 是否仅首次加载，并分别保留 camera-reset 与 routing-stall 的结果；PC-exit/DTR 另作场景记录，不并入这 40 轮。

## 复现

单元测试使用临时 JSON fixture，不读取 Git 忽略的 captures/build；它们验证同一 `build_summary(root=...)` 提取路径中的隔离、null、隐私和失败保留规则，可在干净克隆运行。真实汇总则需要本机保留下面固定 allowlist 中的原始证据和构建产物；缺少任何必需文件会报错退出，不扫描目录或选择“最新”结果：

```powershell
python -m unittest sim.tb.test_benchmark_summary -v
# 仅在拥有全部 allowlist 本地证据的工作区执行真实汇总：
python prj/collect_benchmark_summary.py
```

本次独立 fixture 单测 12/12 通过；本机真实证据汇总生成 10 条记录。前者不是实测，后者只是已列证据的脱敏索引。

原始串口日志、G6 captures、G7 原始 runs、个人录像/照片、构建目录不会被复制进公开 JSON。JSON 只含仓库相对证据索引和哈希；路径在证据工作站可用于定位，未附载原始素材。
