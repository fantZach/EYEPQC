# Android 0.9.0 · 项目 v1.1.0

本次提供可安装的 **Debug 签名 APK**，包名 `org.eyepqc.mobile`，versionCode 10，最低 Android 8.0/API 26。
它不是商店或生产签名版本；未取得外部正式签名材料，不发布 unsigned APK 作为安装包。

## 安装和连接

从本次 Android ZIP 取得 `EYEPQC-Android-0.9.0-debug.apk`，按发布清单核对 SHA256 后安装。
已有应用优先覆盖安装；需包名和签名一致、versionCode 不降低。签名冲突时联系部署者，避免卸载丢失保存的板卡指纹。

此公开 APK 的服务地址为空，**只信系统 CA**。连接前向管理员取得实际可信 WSS 地址及账号密码。
若服务使用自有 CA，部署者须按 [高级教程](DEPLOYMENT_ADVANCED.md) 显式传入公开 CA 重新构建；不关闭证书校验。
APK 不含真实服务地址、部署 CA、账号密码或私钥。登录后自动获取公开配对信息，手机完成 ML-KEM 握手和 AES-GCM 视频解密。

日常操作见 [新手教程](DEPLOYMENT.md)。停止、失败、换钥和切后台清除旧画面；当前仅支持前台观看。

## 交付内容与边界

- 可安装 Debug APK、教程、完整第三方声明及 `licenses/`。
- `manifest.json` 记录 APK 哈希、签名公开指纹、组件版本、源码 commit 和验证边界。
- 默认系统信任，不含部署专用证书；自有 CA 变体由部署者私下构建，不混入公开包。
- 仅交付软件构建与本地检查证据；本次不新增手机、板卡或公网验收，不声明生产安全。

Debug 签名仅用于测试交付，不能代替长期正式签名管理。[第三方声明](THIRD_PARTY_NOTICES.md) 和许可证必须随包保存。
