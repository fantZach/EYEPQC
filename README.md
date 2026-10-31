# EYEPQC

领航者 CF7020B / Zynq-7020、OV5640、Windows PC 和 Android 组成的加密视频系统。
开发板采集 JPEG 并用 AES-128-GCM 加密；手机与板卡完成 ML-KEM-512 握手，在手机上验证认证标签、解密和显示。
PC 负责账号登录与密文转发，公网服务器通过受限 SSH 隧道透明中转。

```text
摄像头 → 开发板 ⇄ USB Slave ⇄ Windows PC ⇄ 公网 TCP 中转 ⇄ Android
```

## 当前可用版本

2026-10-31，用户确认 SD 本地身份版本可用，并指定为正式版第一版。
板卡上电 → 电脑 `eyepqc run` → 手机登录观看。
此前“第一次连接失败、第二次才成功”的问题，用户已确认修复；这是用户反馈，本次整理未新增实机测试。
其他故障、长时间运行与完整冷启动项目仍按各自实际证据验收，不据此全部通过。

新手从 [四端部署教程](doc/deployment/README.md) 开始；范围见 [版本记录](doc/releases/first-stable.md)。
下载 [v1.1.0](https://github.com/fantZach/EYEPQC/releases/tag/v1.1.0)，安装前请看 [本版说明](doc/releases/v1.1.0.md)。
已有 GitHub [v1.0.0](https://github.com/fantZach/EYEPQC/releases/tag/v1.0.0) 是历史开发版，保留原标签与附件。

## 四个子项目

| 子项目 | 内容 |
|---|---|
| [开发板](board/README.md) | 摄像头、RTL、裸机固件、加密、SD 启动 |
| [Windows PC](pc/README.md) | USB/WSS 转发、账号、命令行、安装包与隧道 |
| [Android](mobile/README.md) | 登录、自动配对、ML-KEM、换钥与视频播放 |
| [服务器](server/README.md) | 受限 SSH 透明 TCP 中转 |

板卡继续使用 Vitis Standalone，不需要 Linux、USB 网卡或 PS 网口。局域网观看可省略公网服务器。

## 密钥与账号

固定板端身份私钥及可更新随机状态保存在 SD，日常 PC 不再注入私钥或 seed。
临时 ML-KEM 和视频密钥仍在新连接与换钥时更新；手机提前于 30 分钟上限重新握手。
账号使用 WSS 登录，PC 密码数据库使用加盐 scrypt，同账号新设备需要显式确认接管。
公开配对 JSON 只含连接地址、公钥和指纹，不含密码或私钥。

首次配置材料的电脑仍须可信；本版不提供硬件熵、受保护存储或 SD 克隆/旧快照回滚保护。
不要提交密码、私钥、真实运行材料或视频，详见 [安全说明](SECURITY.md)。

## 开发与验证

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt -r pc/requirements.txt
& ./sim/scripts/run_m00.ps1
git config --local core.hooksPath .githooks
git hook run pre-commit
```

需要 Python 3.12+；C/RTL 检查另需 GCC、Icarus 或 AMD 工具。板端构建使用 Vivado/Vitis 2026.1 和 Zynq-7000 器件包。
提交 hook 保留空白检查及 M00/M10/M12/G5 四项；深度测试按实际改动单独运行。
不要与正在运行的视频服务争抢串口，软件测试不代替板卡或手机验收。

设计入口：[架构](doc/architecture.md)、[字节协议](doc/protocol.md)、[账号/临时 KEM](doc/account_ephemeral_protocol.md)、[实施顺序](doc/steps.md)、[当前进度](report/progress.md)。
四端进阶教程和模块说明继续保留；过时协调、候选和一次性调试记录已移出源码，在维护者本机归档。
文档中的 `203.0.113.10` 和 SSH `22022` 都是示例，必须替换为实际部署值。

[贡献说明](CONTRIBUTING.md) · [第三方许可](THIRD_PARTY_NOTICES.md) · [更新记录](CHANGELOG.md)
自研部分尚未指定统一开源许可证，第三方许可不等于整个项目的授权。
