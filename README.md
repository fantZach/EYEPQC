# EYEPQC

基于领航者 CF7020B / Zynq-7020、OV5640、Windows PC 和 Android 的加密视频 MVP。
板端采集 JPEG 并进行 AES-128-GCM 加密，Android 与板端完成 ML-KEM-512 握手、验 Tag、解密和显示。
PC 提供 USB 接入、WSS 账号登录及密文转发；远程访问使用可选的 OpenSSH 反向隧道。

```text
OV5640 → Zynq-7020 ⇄ USB Slave ⇄ Windows PC ⇄ Android
                                     ⇅          ⇅
                                SSH 反向隧道 → 公网 TCP 中转
```

## 1.0 发布

[下载 v1.0.0](https://github.com/fantZach/EYEPQC/releases/tag/v1.0.0) ·
[发布说明与安装前提](doc/releases/v1.0.0.md) · [更新记录](CHANGELOG.md)

项目版本为 **v1.0.0 开发态 MVP**，组件版本独立：PC **1.3.2**、Android **0.8**。
手机播放及手动换钥已有用户反馈约 **45 fps**，不是持续帧率或全门禁验收。
最新板端 SD 候选仅通过离线检查，尚未上板；首次 USB 查询超时/第二次连接成功的问题仍待实板复测。
本次不分发未验收的 `BOOT.BIN`，板端由源码和构建说明交付。

此仓库当前为私有仓库，Release 下载需要仓库访问权限。发布不改变仓库可见性。

## 四个子项目

| 子项目 | 入口 | 职责 |
|---|---|---|
| 开发板 | [board/](board/README.md) | PL RTL、PS 裸机固件、约束、Vivado/Vitis 构建与板测工具 |
| Windows PC | [pc/](pc/README.md) | USB↔WSS 密文桥、账号管理、CLI/安装包、SSH 上行隧道 |
| Android | [mobile/](mobile/README.md) | 账号登录、自动取得公开配对信息、握手、换钥、解密播放 |
| 服务器 | [server/](server/README.md) | 受限 OpenSSH 透明 TCP 中转及 Linux 部署工具 |

四端共用一个 Git 仓库，不是 submodule。服务器无需接触业务视频密钥；局域网直连无需服务器。
板卡继续使用 Vitis Standalone 与 USB Slave，不需要 USB 网卡或 PetaLinux。

## 开始使用

已配置的 Windows PC 可安装 Release 中的 PC 安装包，并在新终端检查：

```powershell
eyepqc --version
eyepqc config show
eyepqc check
eyepqc account list
```

安装器不包含账号数据库、TLS/SSH 私钥、板端身份或真实 `pairing.json`。
首次部署须先按 [PC 说明](pc/README.md) 准备运行材料；仅下载安装包不能直接启动视频。
Android 附件是含专用公开测试 CA 的 **debug APK**，仅用于受控联测，不是生产签名版本。
板端构建、SD 初始化与联测顺序见 [板端说明](board/README.md) 和 [SD 开发态协议](doc/g6_sd_usb_bootstrap.md)。

开发环境从仓库根目录执行：

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt -r pc/requirements.txt
& ./sim/scripts/run_m00.ps1
# 无板卡软件演示，不代表真机验收
& ./run_demo.ps1 -Mode Demo -Offline
```

需要 Python 3.12+；C/RTL 检查另需 GCC、Icarus 或 AMD 工具。
硬件构建使用 Vivado/Vitis 2026.1 与 Zynq-7000 器件包，接线及工具前提见 [bringup](doc/bringup.md)。
硬件模式会操作板卡，必须先核对接线、镜像和当前服务，不要与运行中的视频服务抢占串口。

## 协议与安全边界

账号模式使用 WSS 和 schema2，配对信息只含公开连接/身份信息，不含登录密码或 token。
板端与 Android 完成身份认证临时 ML-KEM、HKDF 和双向 Finished，长连接每 30 分钟重新握手。
同账号新设备须显式接管；PC 本地密码数据库使用加盐 scrypt。

**当前不是生产安全系统。** 开发态测试身份/seed 由可信 PC 经 JTAG 或显式 USB 初始化提供；
PC 因而仍属于可信调试边界。USB 初始化材料是本地明文，不能宣称对该 PC 的前向保密。
真实板端熵源、生产密钥存储、安全启动/JTAG 防护和完整故障验收尚未闭环。
不要提交或分发私钥、密码、真实运行材料和原始视频。详见 [安全说明](SECURITY.md)。

协议入口：[三端架构](doc/architecture.md)、[字节协议](doc/protocol.md)、
[账号与临时 KEM](doc/account_ephemeral_plan.md)、[公网中转](doc/cloud_relay_plan.md)。

## 验证状态与文档导航

- 实施顺序和剩余门禁：[doc/steps.md](doc/steps.md)。
- 最新进度及原始证据引用：[report/progress.md](report/progress.md)。
- 1.0 的确切验证范围、已知问题和附件：[发布说明](doc/releases/v1.0.0.md)。
- 历史 G7 约 50 分钟实测由用户例外接受，**不是实际满两小时**；故障子项及完整 G8/G9 不据此通过。
- G0 自检 SD 冷启动证据不等于 G6 视频固件完整冷启动验收；历史报告只对各自记录的构建有效。

目录约定：`board/`、`pc/`、`mobile/`、`server/` 为四端，`doc/` 为共享设计，
`sim/` 为共享测试，`data/kat/` 为公开标准向量，`report/` 为历史验证记录。
`build/`、`tmp/`、`.venv/`、`data/captures/`、`board/output/`、`board/vendor/` 是本机忽略目录，不随源码发布。
历史 `src/rtl`、`src/ps`、`src/third_party`、`prj/` 已迁入 `board/`，`src/host` 已迁入 `pc/src/host/`；
旧报告路径/哈希保持原样，不能手改清单把旧产物标成新构建。

## 贡献、许可与提交校验

[贡献说明](CONTRIBUTING.md) · [第三方许可](THIRD_PARTY_NOTICES.md)。
项目自研部分尚未指定统一开源许可证；不能把第三方许可当作整个项目的授权。

```powershell
git config --local core.hooksPath .githooks
git hook run pre-commit
```

提交检查保留暂存空白、M00、M10、M12、G5 四项快速测试；模块深度测试单独执行。
hook 检查当前工作区，部分暂存时应核对提交内容一致；Linux/macOS 首次需给 hook 执行权限。
