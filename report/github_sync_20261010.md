# GitHub 同步范围（2026-10-10）

本轮准备提交隔离 USBPS/CDC EP0 所有权修复、candidate-v4 构建/运行门禁和生成代码 host mock；新增固定来源 G7 审核脚本、脱敏 JSON/报告，并更新 README、进度、验收矩阵、提交检查表和下一阶段任务。

候选 006d 的 180 项哈希预检及短时认证视频通过；camera-reset 与 routing-stall 分别 20/20，同一 manifest/ELF/XSA，恢复时无 JTAG 重载。原始失败尝试仍保留在本地历史证据中；candidate004 枚举失败、candidate005 未上板及早期 006 构建失败均不改写为成功。

本次离线检查：USB bounded SDK 3/3；G6 11/11（包含 2 项 Windows 原子写入测试）；Benchmark fixture 12/12；仓库 pre-commit 要求的 M00 10/10、M10、M12 2/2、G5 1/1 全通过。初次检查因沙箱临时目录写权限失败，改用仓库内忽略的 build/temp 后重跑通过；Benchmark 采用其要求的模块调用方式。源码未因这些环境问题修改。

首次上传受旧沙箱与连接器审批策略限制，远端当时保持 `00722766ec2e1fffea90c8aed6132bf6af523068`。2026-10-10 权限环境恢复后，本机 GitHub 登录重新核验通过，fetch 确认没有远端新提交，正常非强制 push 成功：main 更新为 `556a6591006f2f663397dfb49799192427dae2e4`（19 个文件）。该事实已通过本次 push 输出核验；原始拒绝记录保留在历史对话中。

本地提交和 Git bundle 均保留。该提交的 pre-commit 各项检查由 PowerShell/Python 原生调用完成，并运行 staged diff 检查，没有声称当时 shell hook 自动执行。后续提交仍使用正常 hooks 与非强制推送；若远端更新，先整合新提交，不覆盖协作者。

构建产物、原始 g7_runs/captures、串口载荷、个人照片/录像和秘密数据均不进入提交；无内容变更的既有 `.gitattributes` 状态不纳入本轮。现有 10 条 Benchmark 历史记录保留，006d 的两组批次以独立脱敏摘要关联，未跨构建合并。

后续按用户授权先完成了隔离 Keccak 实板功能/性能测试：实验固件修复、715 项输入/产物哈希核对、软件 1 轮与硬件 3 轮均通过，完整 ML-KEM 硬件路径慢约 8.6%，未集成视频；结束后恢复 006d，140 帧认证视频回归通过。新报告/JSON、UART/JTAG 运行与解析入口、生产安全源审阅/计划、脱敏源码审阅包生成器及内容哈希/路径测试均纳入后续提交。原始 UART/capture/build 留本地，Git 只收脱敏摘要与源码；详见 [实板 Benchmark](keccak_board_benchmark_20261010.md) 和 [材料交付](submission_delivery_plan_20261010.md)。

G7 同构建 PC 退出/DTR 和物理 USB 拔插回归、G0 SD/物理复位/30 分钟冷启动、生产密钥/熵源/全域清零、比赛规则与正式材料仍待完成。执行顺序见 [下一阶段计划](next_stage_plan.md)，006d 的既有恢复结果见 [报告](g7_candidate006d_acceptance_20261010.md)。

## 续推进提交范围

基线 b83ee4e 已正常推送；后续补充 Keccak 配置身份核验/逐次KAT、CPU本地控制缓冲清理与candidate007有限板测，及技术报告事实整理。新实验715项预检、三次实板启动通过但仍慢约8.4%；candidate007 183项预检、双会话284帧和坏Finished拒绝功能回归通过，完整生产安全/G7仍未通过。最终恢复冻结006d并复测140帧；原始capture、ELF与本地开发输入均在ignored目录，Git仅提交源码、测试和脱敏报告。最终Git commit/远端身份与审阅ZIP SHA以独立打包索引为准。
