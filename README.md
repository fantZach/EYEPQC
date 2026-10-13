# EYEPQC

基于领航者 CF7020B / Zynq-7020 与 OV5640 的 JPEG 加密视频系统。
板端使用 Vitis Standalone、ML-KEM-512 和 AES-128-GCM，保留已验证的 USB Slave 传输。
目标链路为 **开发板 → USB → PC → 网络 → 移动端**，远程服务器可选。
平台已确认：**PC 使用 Windows，移动端使用 Android**。

2026-10-13 新阶段：账号密码登录、同账号显式接管、稳定身份认证临时 ML-KEM 公钥、
长连接每 30 分钟重新握手。独立方案与安全前置见 [账号与临时 KEM 方案](doc/account_ephemeral_plan.md)。
此方案正在实现，不代表手机、实板、可信熵源或完整视频 SD 自启动已通过。

```text
OV5640 → 开发板：采集 JPEG / AES-GCM 加密
                  ⇅ USB CDC（密文视频向外，控制消息双向）
                 PC：USB 接入 / 密文转发
                  ⇅ 局域网直连，或经可选公网中转服务
               移动端：ML-KEM 握手 / 验 Tag / 解密 / JPEG 显示
```

先在同一局域网内由 PC 提供接入服务，无需租服务器。公网阶段可将中转服务部署到已有或租用的服务器；
板卡仍通过 PC 联网，无需改成 USB Host 或迁移到 PetaLinux。

## 三个子项目

| 子项目 | 目录 | 职责与当前状态 |
|---|---|---|
| 开发板 | [board/](board/README.md) | 已有 PL RTL、PS 裸机代码、第三方密码核、约束、构建及板测工具 |
| PC | [pc/](pc/README.md) | 原有调试端与新 USB↔WebSocket 纯密文桥；桥已通过软件回环测试，真实 USB 联调待做 |
| 移动端 | [mobile/](mobile/README.md) | Android 调试 APK 已构建并验签，Java/网络互操作通过；实际手机/板卡待验 |

可选远程中转服务归 PC 子项目维护、独立部署，不另设第四个源码子项目。
原有 **板卡↔PC 本地解密演示** 保留；新桥与 Android 核心已通过软件互操作，手机/板卡实机和公网链路尚待验收。
移动端采用原生 Java Activity、OkHttp 4.12.0、Bouncy Castle 1.81 lightweight ML-KEM；最低 Android 8.0/API 26，目标 API 35。

```text
EYEPQC/
├── board/
│   ├── src/rtl/          # 摄像头、AXIS、AES-GCM、独立加速实验
│   ├── src/ps/           # Cortex-A9 裸机固件
│   ├── src/third_party/  # 固定版本密码库及许可证
│   ├── prj/             # Vivado/Vitis 构建、板测和交付工具
│   └── xdc/             # 板级约束
├── pc/src/host/          # 现有 Python 主机与开发验证工具
├── mobile/              # 移动端职责、协议接入与验收计划
├── doc/                 # 共享目标、协议和实施步骤
├── sim/                 # 跨板端/主机的集成测试、RTL testbench、向量
├── data/kat/            # 公开标准测试向量
├── report/              # 历史证据与当前进度
├── skill/               # 项目协作技能
├── requirements.txt     # 共享 Python 开发/验证环境
└── run_demo.ps1          # 仓库级快捷入口
```

`build/`、`data/captures/`、`board/output/`、`board/vendor/` 和 `.venv/` 保留原位置并继续由 Git 忽略。
三子项目是同一 Git 仓库中的职责划分，不是 Git submodule；`sim/` 为共享验收设施。

## 快速开始：现有 PC 基线

以下命令均从仓库根目录执行，需要 Python 3.12+；C/RTL 检查另需 GCC、Icarus 或相应 AMD 工具。

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
& ./sim/scripts/run_m00.ps1
# 无板卡的演示窗口（软件参考，不是手机端或实板验收）
& ./run_demo.ps1 -Mode Demo -Offline
# 完整电脑端回归；工具位置按本机安装调整
& ./run_demo.ps1 -Mode Check -ToolRoot 'D:/AmdDesignTools/2026.1'
```

接线与重新构建见 [bringup](doc/bringup.md)，GUI 录像/回放见 [演示说明](doc/demo.md)，
固定图片加密见 [AES MVP](doc/aes_mvp.md)。`run_demo.ps1` 默认 `Check`，也支持 `Build`、`Prepare`、
`Preflight`、`JtagCheck`、`G3`、`G6`、`G7`、`Demo`。硬件模式会操作板卡，执行前须核对构建与接线。

## 新链路与安全边界

目标模式下，移动端固定校验板卡公钥，与板卡完成 ML-KEM、双向 Finished 和会话控制。
PC/中转服务只路由原样控制记录和加密视频，不持有业务会话密钥；接收端验 Tag、反重放后才显示完整 JPEG。
现有 `pc/src/host/handshake.py` 与 `g6_board.py` 是迁移参考和调试基线，不能直接当作纯转发器运行。

当前开发态由 PC 经 JTAG 注入测试私钥/seed，PC 因而仍在可信调试边界内。
真实板端熵源、生产密钥存储及生命周期、secure boot/JTAG 防护和全域清零尚未闭环。
仅搬移握手代码不能宣称 PC 不可信场景下已具备生产级端到端安全。

新链路的职责、双向路由、会话断连和验收规则见 [三端架构](doc/architecture.md)，
准确字节格式仍以 [协议](doc/protocol.md) 为准，实施顺序见 [steps](doc/steps.md)。

## 已有证据与待完成工作

- 历史 G6 开发态 USB 动态握手、认证视频与换钥通过，视频约 47 fps；不代表手机端帧率。
- G7 原 2 小时长期子项由用户对约 50 分钟实测作例外验收，未实测满 2 小时；G0/G7 整体仍未通过。
- candidate014 仅离线候选，板测与故障恢复门禁待做；独立 Keccak 加速实验未集成到正式视频工程。
- PC 密文桥与 Android 调试 APK 已有，局域网三端软件互操作已验证；真实板卡/手机和 45 fps 待验，可选公网中转未实现。

最新变更与验证见 [progress](report/progress.md)，板测细节见 [下一阶段计划](report/next_stage_plan.md)、
[验收矩阵](report/acceptance_matrix_20261009.md) 和 [G6](doc/g6.md)。历史报告只对其记录的构建有效。

## 目录迁移与构建注意事项

2026-10-12 起：`src/rtl`、`src/ps`、`src/third_party` 移至 `board/src/`，
`prj/` 移至 `board/prj/`，`src/host/` 移至 `pc/src/host/`。
当前文档命令、构建入口和测试路径已同步调整；`report/` 的历史命令、路径与哈希保留为当时证据，
重现时需按上述映射转换。根目录 `run_demo.ps1` 与 G7 启动脚本继续可用。

旧 `build/` 的工程、XSA/ELF 和 manifest 不做自动改写。旧路径或源码哈希不匹配时预检会拒绝，
请按新目录在新的输出目录重建所需硬件/软件，再进行板测；不可手改清单将旧产物标成新构建已验证。

## Git 提交校验

```powershell
git config --local core.hooksPath .githooks
git hook run pre-commit
```

提交时保留暂存空白检查及 M00（含向量一致性）、M10、M12、G5 四项快速检查。
需要本地 `.venv` 与 GCC，不需要板卡。涉及其他模块时单独运行对应深度测试。
hook 检查当前工作区，部分暂存时应核对工作区与提交内容一致；Linux/macOS 首次需赋予 hook 执行权限。
