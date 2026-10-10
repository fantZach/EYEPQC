# 竞赛材料与提交包交付计划

更新：2026-10-10。本文是现有仓库与本地证据的归档方案，不代表组委会审核，也不臆造论文、PPT、视频、格式、命名或评分要求。当前没有提供正式比赛规则、模板、截止时间和提交平台信息；正式成品类型须待规则核实后确定。现阶段可以独立整理的范围是源码快照、已有技术/验收报告、脱敏证据索引与文件 hash 清单。

## 当前可用材料与证据位置

| 内容 | 当前文件/状态 | 交付口径 |
|---|---|---|
| 项目目标、系统结构和威胁模型 | `README.md`、`doc/goals.md`、`doc/description.md`、`doc/steps.md`、`doc/protocol.md` | 可作为技术背景与复现入口；需按正式规则决定是否编成论文或设计说明，不自动新增摘要、结论等结构。 |
| 主要实现 | `src/rtl/`、`src/ps/`、`src/host/`、`src/third_party/` | 源码在仓库中；`build/` 被 `.gitignore` 排除，构建物不属于当前源码提交。 |
| 仿真/复跑入口 | `run_demo.ps1`、`prj/`、`sim/`、`sim/vectors/`、`data/kat/`、`requirements.txt` | 保留脚本、版本/依赖说明和公开测试向量。复跑必须使用相同源码与工具版本；离线 PASS 不代表板卡验收。 |
| 当前离线构建凭证 | `report/software_ready.md`；本机 `build/vitis/software_ready/software_verification.json`、`build_manifest.json` 与对应产物 | 报告记录的软件入口、哈希预检和软件检查可作为电脑端证据。机器文件位于忽略目录，离开本机/干净克隆即不存在；在证据归档时需从本机导出清单及选定文件并重算 hash。构建 manifest 保留 `board_validated=false`，不当作实板通过。 |
| 最新 006d 板测汇总 | `report/g7_candidate006d_acceptance_20261010.md` 和 `.json` | 本次 candidate006d 的 camera-reset、routing-stall 各 20/20 通过，短测 471 帧。PC 退出/DTR 20 次、物理 USB 拔插 20 次仍待同构建复测。仅能按受控恢复场景提交。 |
| G0 启动证据 | `report/g0_acceptance.md`、`report/acceptance_matrix_20261009.md` | 记录临时 JTAG 探测和局部 DDR/timer/LED 证据；SD 独立启动、物理复位、30 分钟冷启动未通过/未验收。原始 capture 在 `data/captures/`，受 `.gitignore` 排除，应先做隐私/身份审查再决定是否单独封存。 |
| Benchmark 与脱敏摘要 | `report/benchmark_summary_20261009.md`、`.json`、`report/parallel_B_20261009.md`、`report/parallel_C_20261009.md` | 使用摘要中的源状态、构建身份和 `null` 字段；历史构建、开发态功能、离线/实测分列。新增板级证据见 `report/keccak_board_benchmark_20261010.md/.json`：safeSW 1 轮、safeHW 3 轮及 3 次启动的 tcId 76 Decaps 对照通过；HW 平均约 1.172 ms，SW 约 1.079 ms，HW 慢约 8.6%，无加速收益。范围仅 tcId 76，不代表全部 84 个向量的板上验证；STATUS 清零读回不证明设备全域清零；未集成视频工程。 |
| 用户演示 | `report/demo_software_ready.md`、相关 `report/` 记录；实机 15 秒录像为 722/722 帧保存并解码 | 只能表述当前短录像与软件功能证据；长录像和最终比赛演示视频尚未完成。原始视频/照片不默认进入公开包。 |
| 技术报告草稿 | `report/technical_report.md`、`report/collaboration_log.md` | 是仓库草稿与过程索引，不应标作最终论文；需完成技术事实复核、表达与格式整理后再按规则转成正式材料。 |
| Keccak 独立验证 | `report/keccak_accel.md`、`report/keccak_board_benchmark_20261010.md/.json`、`doc/keccak_accel.md`、实验源 `src/ps/experimental/` 与 `src/rtl/crypto/keccak*` | 可以作为“隔离原型/离线验证及有限板级功能测试”附件。板级 tcId 76 功能路径通过，但本次硬件路径平均慢约 8.6%；不得宣称加速收益，也不得外推到其他向量、视频工程或全域设备零化。 |
| 生产安全 | `report/security_gap_audit.md` 与本计划 [安全闭环计划](production_security_plan_20261010.md) | 明确标记未完成；开发态 JTAG 注入、熵源和全域清零缺口必须作为限制披露，不能写成生产安全能力。 |
| Git 同步状态 | `report/github_sync_20261010.md` | 该报告记录整理时的历史状态；当前 source HEAD `556a6591006f2f663397dfb49799192427dae2e4` 已推送 GitHub（依据本轮交付协调状态）。新加或工作树修改的交付文件须另外核对 commit 与远端，不能因基线已推送而称本轮所有产物均已发布。 |

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
2. 从 `report/` 选择当前有效的索引与报告，以 `acceptance_matrix_20261009.md` 和 `g7_candidate006d_acceptance_20261010.md/.json` 为主入口；按“源码/仿真、电脑构建、板上实测、待测”分别整理，保留失败和未测项。
3. 仅挑选不含密钥、主机路径、个人资料、原始 USB/串口载荷和无关录像的脱敏证据。对另行封存的本机原始数据，记录原路径、脱敏派生文件和 hash；原始文件留在本地证据库，不因做公开摘要而删除。
4. 对所选构建产物记录 variant、XSA/ELF/BOOT.BIN/bitstream hash、对应源码 manifest、`board_validated` 值及板卡验证状态。若无法重现当前身份，则注明是历史产物，不借用最新板测结果替旧构建背书。
5. 生成最终文件 manifest 与目录清单，做一次缺文件/零字节/意外秘密/忽略产物检查；交付前只对最终选定目录生成压缩包，并保留原始目录供复核。若规则限制大小，按必需与可选附件分包，不降低证据准确度。

## 待规则确定的项目

以下均没有当前可核实的赛方来源，不能预设：参赛类别与评分项、论文/设计说明要求、模板与页数、答辩 PPT、演示视频时长/编码、代码或构建产物是否提交、附件格式/容量/命名、匿名或署名规则、AI 使用声明、截止时间、平台以及实测证据的接受形式。收到正式规则后，按条款映射到本地证据，列出逐条满足/缺失/需现场完成，并以最新规则原文为准。

当前阶段可以生成本地审阅包并归档源码、脱敏测试摘要和报告索引；不能宣称规则符合性或材料已正式提交。最终演示视频、006d 未完成的 USB/PC 回归、G0 SD/复位/30 分钟证据及生产安全认证仍未完成。Keccak 板级功能测试已有有限结果，但硬件路径慢约 8.6%，没有性能收益；仅完成 tcId 76 的 3 次启动测试，不外推到其他向量或视频链路。正式比赛规则和截止时间未提供，当前包仅用于审阅与证据留档。
