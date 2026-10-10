# GitHub 同步范围（2026-10-10）

本轮准备提交隔离 USBPS/CDC EP0 所有权修复、candidate-v4 构建/运行门禁和生成代码 host mock；新增固定来源 G7 审核脚本、脱敏 JSON/报告，并更新 README、进度、验收矩阵、提交检查表和下一阶段任务。

候选 006d 的 180 项哈希预检及短时认证视频通过；camera-reset 与 routing-stall 分别 20/20，同一 manifest/ELF/XSA，恢复时无 JTAG 重载。原始失败尝试仍保留在本地历史证据中；candidate004 枚举失败、candidate005 未上板及早期 006 构建失败均不改写为成功。

本次离线检查：USB bounded SDK 3/3；G6 11/11（包含 2 项 Windows 原子写入测试）；Benchmark fixture 12/12；仓库 pre-commit 要求的 M00 10/10、M10、M12 2/2、G5 1/1 全通过。初次检查因沙箱临时目录写权限失败，改用仓库内忽略的 build/temp 后重跑通过；Benchmark 采用其要求的模块调用方式。源码未因这些环境问题修改。

GitHub 上传尚未完成。远端 main 已核验为 `00722766ec2e1fffea90c8aed6132bf6af523068`，本次未改动远端。连接器可读取且仓库授权包含 push，但创建 Git tree 被工具环境拒绝：`MCP tool call requires approval, but approval policy is never`。本机 Git 的 MSYS shell/CLI 凭据路径也受沙箱限制，本机 GitHub CLI 登录检查未通过。

本地提交和 Git bundle 保存已完成工作。pre-commit 的各项检查由 PowerShell/Python 原生调用完成，并运行 staged diff 检查；没有声称 shell hook 自动执行。待恢复有效本机登录或连接器写入审批后，重新 fetch/核对远端，再非强制推送；若远端已更新，先整合新提交，不覆盖协作者。

构建产物、原始 g7_runs/captures、串口载荷、个人照片/录像和秘密数据均不进入提交；无内容变更的既有 `.gitattributes` 状态不纳入本轮。现有 10 条 Benchmark 历史记录保留，006d 的两组批次以独立脱敏摘要关联，未跨构建合并。

G7 同构建 PC 退出/DTR 和物理 USB 拔插回归、G0 SD/物理复位/30 分钟冷启动、Keccak 实板功能与性能、生产密钥/熵源/全域清零、比赛规则与最终材料仍待完成。执行顺序见 [下一阶段计划](next_stage_plan.md)，完整当前结果见 [006d 报告](g7_candidate006d_acceptance_20261010.md)。
