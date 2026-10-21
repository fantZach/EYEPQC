# 更新记录

## v1.0.0 — 2026-10-21

首次项目级发布，定位为开发态 MVP；组件版本保持 PC 1.3.2、Android 0.8。

- 四端目录：板端 `board/`、Windows `pc/`、Android `mobile/`、中转 `server/`。
- OV5640 JPEG → 板端 AES-GCM → USB → WSS → Android 解密播放；真实手机短测由用户反馈约 45 fps。
- 账号密码登录、自动取得公开配对、显式接管、身份认证临时 ML-KEM-512、HKDF/双向 Finished、定时及手动换钥。
- Windows CLI/用户级安装器、配置和本地账号管理；可选 OpenSSH 公网透明中转。
- SD 开发态启动/USB 初始化实现与离线检查；最新 CLEAR_HALT 候选仍待上板，不附板端二进制。
- 整理当前入口、安装前提、安全边界、第三方许可及发布说明，保留历史证据。

已知限制：首次 USB 查询仍可能超时；Android 附件为 debug APK；PC 安装需要受保护的运行材料；
生产熵源/身份存储等未闭环，完整冷启动、故障及持续公网门禁未全部验收。
详见 [v1.0.0 发布说明](doc/releases/v1.0.0.md)。
