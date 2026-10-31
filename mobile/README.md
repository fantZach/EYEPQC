# Android 子项目

手机负责账号登录、自动获取公开配对信息、ML-KEM 握手、换钥、认证解密与 JPEG 视频显示。
普通使用见 [新手部署](DEPLOYMENT.md)，构建、证书与签名见 [进阶教程](DEPLOYMENT_ADVANCED.md)。

## 当前流程

输入管理员提供的可信 WSS 地址和账号密码，APP 从同地址 HTTPS 获取公开 schema2，然后建立 WSS 视频连接。
固定身份握手后，板卡提供经过认证的临时 ML-KEM 公钥，双方派生业务密钥并再次 Finished，再 START。
每次连接/接管重新握手，约 1785 秒主动换钥，板端 1800 秒硬截止。
停止、失败、换钥和切后台清除旧画面；显式接管，不自动抢回账号，不后台播放。
画面显示 FPS、认证帧和缺片帧；显示 FPS 不是板卡发送率，需与认证帧和网络统计一起判断。

用户确认当前 SD 版本连接可用，并反馈此前首次连接问题修复；本次整理未新增 Android 真机测试。

## 构建与信任

源码组件版本独立于项目正式版名称。最低 Android 8.0/API 26，JDK 17+、Gradle 8.9、编译 SDK 35。
当前源码的 Debug 和 Release 默认均只信系统 CA，不内置实际服务器地址或专用部署 CA。
自有 IP/测试 CA 必须由安装负责人通过 `mobile/build.ps1 -TrustCaFile <公开CA路径>` 显式提供。
这只导入公开 CA，不得把 CA 私钥或服务器私钥放入 APK；保留证书地址、期限和链校验。
Release 必须使用外部正式签名材料；unsigned APK 不能安装，Debug 签名不能冒充正式签名。
这次源码默认值清理不自动改变已安装手机或已发布 APK，部署前须重新构建、核对并安装。

## 代码与验证

原生 Java Activity、OkHttp 与 Bouncy Castle ML-KEM，协议和密码内核测试与 UI 生命周期分别验证。
公开配对设置可保存，密码只在当前进程使用；已保存指纹变化拒绝静默接受。
HTTPS 配对拒绝明文、重定向、跨地址、超长配置、错误摘要和证书；账号只在 TLS 内发送。
每条 WebSocket 二进制消息承载完整 USB 记录，组帧后验证 GCM 标签才解密显示。
协议见 [suite2](../doc/account_ephemeral_protocol.md)，安全范围见 [SECURITY](../SECURITY.md)。

[第三方许可](THIRD_PARTY_NOTICES.md) · [历史 v1.0.0 交付说明](RELEASE.md)
