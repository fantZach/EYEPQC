# 竞赛材料与提交包交付计划

更新：2026-10-11。本文是现有仓库与本地证据的归档方案，不代表组委会审核，也不臆造论文、PPT、格式、命名或评分要求。赛事协办方高云的 2026 页面列出 FPGA 创新设计赛道、报名截止 2026-09-22 24:00、作品提交 2026-11-04 18:00、决赛 2026-11-20 至 22 日；青岛科技大学微电子学院通知列出相同节点。[高云赛程页面](https://www.gowinsemi.com.cn/university/match2026)；[高校通知](https://wdz.qust.edu.cn/info/1055/1203.htm)。官方公开规则核验结论见[独立记录](contest_rules_review_20261011.md)：竞赛官网检索到的 MP4/PDF/RAR 具体限制属于芯片应用赛道，不能套用到本项目 FPGA AMD 赛道。AMD 赛道正式细则、提交格式和队伍资格仍需以 FPGA 竞赛官网/报名后台最新文件为准。

## 当前可用材料与证据位置

| 内容 | 当前文件/状态 | 交付口径 |
|---|---|---|
| 项目目标、系统结构和威胁模型 | `README.md`、`doc/goals.md`、`doc/description.md`、`doc/steps.md`、`doc/protocol.md` | 可作为技术背景与复现入口；需按正式规则决定是否编成论文或设计说明，不自动新增摘要、结论等结构。 |
| 主要实现 | `src/rtl/`、`src/ps/`、`src/host/`、`src/third_party/` | 源码在仓库中；`build/` 被 `.gitignore` 排除，构建物不属于当前源码提交。 |
| 仿真/复跑入口 | `run_demo.ps1`、`prj/`、`sim/`、`sim/vectors/`、`data/kat/`、`requirements.txt` | 保留脚本、版本/依赖说明和公开测试向量。复跑必须使用相同源码与工具版本；离线 PASS 不代表板卡验收。 |
| 当前离线构建凭证 | `report/software_ready.md`；本机 `build/vitis/software_ready/software_verification.json`、`build_manifest.json` 与对应产物 | 报告记录的软件入口、哈希预检和软件检查可作为电脑端证据。机器文件位于忽略目录，离开本机/干净克隆即不存在；在证据归档时需从本机导出清单及选定文件并重算 hash。构建 manifest 保留 `board_validated=false`，不当作实板通过。 |
| 最新 G7 板级诊断与软件候选 | `report/g7_candidate012_tx_ownership_board_20261011.md`、`report/g7_candidate014_safe_hello_ack_retry_offline_20261011.md` | candidate012 receiver-exit 20 轮批次停在 13/20，两次 HELLO_ACK 超时；candidate014 的安全重试、候选构建、预检与软件回归已完成，`board_validated=false`。普通 CDC 重连不是 G7 通过证据；candidate014 新板基线、ETW/AP0 单轮、20 次 receiver-exit 和后续 USB 物理拔插尚未完成。旧 006d camera-reset/routing-stall 各 20/20 只作为原构建历史证据。 |
| G0 启动证据 | `report/g0_acceptance.md`、`report/acceptance_matrix_20261009.md` | 记录临时 JTAG 探测和局部 DDR/timer/LED 证据；SD 独立启动、物理复位、30 分钟冷启动未通过/未验收。原始 capture 在 `data/captures/`，受 `.gitignore` 排除，应先做隐私/身份审查再决定是否单独封存。 |
| M02 冷启动和无摄像头 fail-closed | `report/m02_sensor_reset_board_20261011.md`、`report/m02_coldboot_cycles_20261011.json`、`report/m02_camera_absent_20261011.json` | 用户确认的 20 次整板断电/上电后 JTAG 配置 20/20，另有无摄像头 fail-closed 通过；没有写 SD/Flash。不能外推到 SD 独立启动或 DVP/JPEG 实拍。 |
| Benchmark 与脱敏摘要 | `report/benchmark_summary_20261009.md`、`.json`、`report/parallel_B_20261009.md`、`report/parallel_C_20261009.md` | 使用摘要中的源状态、构建身份和 `null` 字段；历史构建、开发态功能、离线/实测分列。新增板级证据见 `report/keccak_board_benchmark_20261010.md/.json`：safeSW 1 轮、safeHW 3 轮及 3 次启动的 tcId 76 Decaps 对照通过；HW 平均约 1.172 ms，SW 约 1.079 ms，HW 慢约 8.6%，无加速收益。范围仅 tcId 76，不代表全部 84 个向量的板上验证；STATUS 清零读回不证明设备全域清零；未集成视频工程。 |
| 用户演示 | `report/demo_software_ready.md`、相关 `report/` 记录；实机 15 秒录像为 722/722 帧保存并解码 | 只能表述当前短录像与软件功能证据；长录像和最终比赛演示视频尚未完成。原始视频/照片不默认进入公开包。 |
| 技术报告草稿 | `report/technical_report.md`、`report/collaboration_log.md` | 是仓库草稿与过程索引，不应标作最终论文；需完成技术事实复核、表达与格式整理后再按规则转成正式材料。 |
| 可复用 Skill | `skill/eyepqc-fpga/SKILL.md`、`skill/eyepqc-fpga/README.md` | 新增独立 README、调用流程、构建哈希/时序/DMA/G7 案例、验证结果和失效边界；仅验证了与本仓库现有证据的一致性，尚无外部团队迁移测试。 |
| 开源与许可证准备 | [初步盘点](reuse_license_audit_20261011.md)；当前根目录没有项目级 `LICENSE`；第三方目录分别保留 `src/third_party/tinycrypt/LICENSE`、`src/third_party/mlkem/LICENSE`、`src/rtl/crypto/secworks_aes/LICENSE` | 已做初步文件盘点，不能据此判断整个工程授权兼容或选择项目许可证。仍需完整版权/依赖审查、团队权利人确认与发布授权；仓库可见性未在本轮变更。 |
| Keccak 独立验证 | `report/keccak_accel.md`、`report/keccak_board_benchmark_20261010.md/.json`、`doc/keccak_accel.md`、实验源 `src/ps/experimental/` 与 `src/rtl/crypto/keccak*` | 可以作为“隔离原型/离线验证及有限板级功能测试”附件。板级 tcId 76 功能路径通过，但本次硬件路径平均慢约 8.6%；不得宣称加速收益，也不得外推到其他向量、视频工程或全域设备零化。 |
| KX41 ML-KEM-512 60 组板测 | `report/keccak_sponge_x4_capture_fix_20261011.md/.json` | 独立 KX41 候选在软件、硬件、超时回退三窗口各覆盖 60/60 KAT；硬件窗口 0 回退、计时为软件的 88.6%。这是独立候选的 KAT/性能结果，不代表视频固件集成或内部 STATE/OUTPUT 清零已证明。 |
| 生产安全 | `report/security_gap_audit.md` 与本计划 [安全闭环计划](production_security_plan_20261010.md) | 明确标记未完成；开发态 JTAG 注入、熵源和全域清零缺口必须作为限制披露，不能写成生产安全能力。 |
| Git 同步状态 | `report/github_sync_20261010.md` | 该报告是历史记录。每次交付前后都应重新核对当前分支、HEAD 与远端；不得以历史同步记录代替本次状态。`.gitattributes` 的既有本地修改不属于本交付范围，不得顺手暂存。 |

原始硬件捕获、`report/g7_runs/`、`build/` 均被 `.gitignore` 排除。部分记录路径是本机证据，普通 Git 克隆不包含。仓库内机器可读脱敏摘要和报告可供审阅，但不得从这些摘要倒推出未附带的原始数据仍可在另一台机器复算。

## 建议归档目录

按实际可交付内容建立独立只读目录，文件名先采用中性占位，不宣称官方命名：

```text
EYEPQC_submission_draft_20261010/
├── README_delivery.md                 # 内容、版本、状态边界、重现入口
├── source_snapshot/                   # 指定 Git commit 的源码快照，不含 build/ 和秘密
├── reports/
│   ├── project_scope_and_protocol.md  # 从现有文档整理，规则未明时先不改写成论文
│   ├── verification_matrix.md         # 指向原报告的状态汇总
│   ├── production_security_status.md  # 当前未通过及已知边界
│   └── evidence_index.md              # 相对路径、证据类型、构建身份、状态、hash
├── evidence/
│   ├── sanitized/                     # 已纳入仓库的脱敏 JSON/汇总
│   └── build/                         # 仅在确认交付需要时纳入所选构建产物及 hash
└── manifest.sha256                   # 对最终归档内每个文件计算的 hash
```

此结构是本地工作稿方案，不是赛方模板。`reports/` 可先由现有索引和报告形成可审阅档案；是否把 `source_snapshot`、BOOT.BIN/ELF/bitstream 放进正式上传包，应根据规则、大小限制、复现要求以及版本/器件身份复核后确定。被 `.gitignore` 排除的 capture、私有构建目录、照片、录像、JTAG provision 输入、私钥、随机种子和任何 token 不直接复制进包。

## 电脑端可先完成的归档工作

1. 固定归档使用的源码 commit/工作树状态，并记录 Git commit、源码文件清单及 SHA-256；若归档包含未提交改动，逐项说明来源和状态，不把它们混成“发布版本”。
2. 从 `report/` 选择当前有效的索引与报告，以 `acceptance_matrix_20261009.md`、`g7_candidate012_tx_ownership_board_20261011.md`、`g7_candidate014_safe_hello_ack_retry_offline_20261011.md`、`keccak_sponge_x4_capture_fix_20261011.md` 和 M02 记录为主入口；按“源码/仿真、电脑构建、板上实测、待测”分别整理，保留失败和未测项。
3. 仅挑选不含密钥、主机路径、个人资料、原始 USB/串口载荷和无关录像的脱敏证据。对另行封存的本机原始数据，记录原路径、脱敏派生文件和 hash；原始文件留在本地证据库，不因做公开摘要而删除。
4. 对所选构建产物记录 variant、XSA/ELF/BOOT.BIN/bitstream hash、对应源码 manifest、`board_validated` 值及板卡验证状态。若无法重现当前身份，则注明是历史产物，不借用最新板测结果替旧构建背书。
5. 生成最终文件 manifest 与目录清单，做一次缺文件/零字节/意外秘密/忽略产物检查；交付前只对最终选定目录生成压缩包，并保留原始目录供复核。若规则限制大小，按必需与可选附件分包，不降低证据准确度。

## 尚待官方材料确认的项目

提交截止时间已由赛事协办方赛程页和高校通知列出为 2026-11-04 18:00；日程仍可能更新，应以 FPGA 竞赛官网最新通知和报名后台为准。AMD 赛道报告/视频/代码的模板、页数/时长、编码、容量、命名、匿名要求、代码与构建物上传范围、官方平台步骤及具体评分细则仍需核实。竞赛官网发布的“2026 年应用赛道作品上传要求”对应另一条赛道，不直接应用于本项目。附件中关于开源协议、Skill 与大模型协作记录的要求来自一份公开指南转录，暂不能直接当作赛方最终要求；应取得相应 AMD 赛道官方文件后逐条映射。另需由队长后台确认报名和资格审核状态。技能包 README 与协作记录已补齐初版；根目录许可证选择和对外公开仍未完成，需完整权利审查与团队确认。

当前阶段可以生成本地审阅包并归档源码、脱敏测试摘要和报告索引；不能宣称规则完全符合或材料已正式提交。演示视频和正式报告未定稿；G7 receiver-exit 与物理拔插回归、G0 SD/复位/30 分钟证据、生产安全认证仍未完成。KX41 已有 60/60 三窗口独立候选板测，硬件窗口耗时为软件的 88.6%，但不能外推到视频固件集成或内部状态清零。截止时间已核实为 2026-11-04 18:00，正式材料细则及报名资格仍需从最新官方渠道确认。
