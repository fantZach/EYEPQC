# Android 0.9.0-rc1 候选交付

本包是待用户统一验收的候选，不是稳定版验收结论。项目 v1.1.0-rc1 与 Android 组件版本独立。

## 包内文件

- `debug/EYEPQC-Android-0.9.0-rc1-debug.apk`：可安装调试版，沿用已有 Debug 签名与专用测试 CA。
- `release-unsigned/EYEPQC-Android-0.9.0-rc1-release-unsigned.apk`：默认系统 CA-only、禁止调试/明文流量的未签名构建，**不可安装**。
- `manifest.json`：两包哈希、签名/信任类型、待验收状态。未包含真实部署 CA 或正式签名。
- `DEPLOYMENT.md`：从 SDK、IP WSS 专用 CA、正式签名到登录、升级、回滚和用户验收的步骤。
- `THIRD_PARTY_NOTICES.md` 与 `licenses/`：二进制分发必须保留的许可。

不包含集成测试临时 CA、临时签名 APK、keystore、密码、板端私钥/seed 或真实配对信息。
正式候选还需要操作者提供长期管理的 Android 签名 keystore、别名/密码和与 PC 叶证书匹配的部署公开 CA；
脚本不自动建立或替换这些真实身份，不使用 Debug key 充数。

## 软件检查（2026-10-31）

- `mobile/test.ps1`：核心 160、配对 57、临时 KEM 37、UI 状态 49、新增连接诊断 7，共 310 项断言通过。
- `python mobile/test/test_auto_pairing.py`：10 个 HTTPS 自动配对/拒绝场景通过。
- `python mobile/test/test_cloud_endpoint.py`：4 个本机 TLS/SAN/HTTP 拒绝/接管场景通过。
- `python mobile/test/test_release_build.py`：3 组 Gradle 离线集成测试通过，102.4 秒，无 skip。
  包含私钥/多证书/叶证书/过期/旧 debug CA 拒绝、部分签名值拒绝、显式公开 CA 与系统 CA-only 资源隔离、
  外部临时 fixture 签名和 SDK 验签、缺签名直接失败、输出不覆盖。所有 fixture 都不进入交付包。
- 实际 debug/release 构建、release vital lint、Debug APK v2 签名和最终 CA 隔离检查通过。
  保留现有 JDK source/target 8 弃用及缺 platform-tools 提示，不声称零警告。

测试与构建要求完整的本机 JDK/Gradle/SDK 依赖缓存；见部署教程。
新增集成测试缺这些前置时明确 skip，不把跳过算通过。
早期检查曾假定 release 的资源路径不变而失败；最终检查从 aapt 资源表解析优化后的真实路径。
TLS 测试旧版断言通用“连接失败”文案，现已同步检验 TLS 分类；认证/拒绝和清理条件未放宽。

## 仍待用户/部署材料

Android 真机布局/全屏/旋转/前后台、首连与重连、错密码/错误证书/身份变化拒绝、手动/定时换钥、接管、
持续帧率和故障恢复由用户统一验收。板端首次 USB 查询故障仍待实板结论，手机不无限自动重试。
原调试 CA 在 2026-11-12 16:59:03 UTC 到期；当前实际 PC 叶证书期限需另行检查，可能更早到期。
正式签名与专用部署 CA 缺失时只交 unsigned，不发布“正式安装 APK 已完成”的结论。
当前开发 PC 仍知道板端测试身份/seed；非调试构建不等于生产安全或对该 PC 的前向保密。
