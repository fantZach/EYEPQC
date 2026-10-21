# Android 0.8 · 项目 v1.0.0 开发态交付

## 安装与连接

使用项目 Release 中明确标注 `0.8-debug` 的 Android 开发包，最低 Android 8.0（API 26）。
核对发布页 SHA-256 后覆盖安装；相同 Debug 签名可保留已有公开配对设置，不必先卸载。
首次使用仍须由部署者提供可信 WSS 地址和独立创建的账号密码；应用内默认公网地址只是当前开发入口，
不表示公共服务承诺。不要向聊天、日志、配对 JSON 或 URL 写入密码。

输入账号密码后，应用从同地址 HTTPS 获取公开 schema2 配对信息，再进行 WSS 登录和 suite2 握手。
密码只在当前进程使用，不随 APK 或配对文件分发。停止、失败、换钥和切后台会清除旧画面；只支持前台单观看端。
协议、部署和 UI 操作详见 [仓库 README](https://github.com/fantZach/EYEPQC/blob/v1.0.0/mobile/README.md)。

## 包与安全限制

- 包名 `org.eyepqc.mobile`，versionName `0.8`，versionCode `8`，minSDK 26 / targetSDK 35。
- 本包是 Android Debug 签名，`debuggable=true`，内置一个专用公开测试 CA；不是商店/生产签名 APK。
- CA DER SHA-256：`263c8c06420a2b72726d93c746766d3efd8040fe6d711af49f240ebbc1b4dc8b`。
  有效期至 2026-11-12 16:59:03 UTC（北京时间 2026-11-13 00:59:03），到期须重新准备可信开发证书/构建，不能关闭校验。
- debug-overrides 只增加开发 CA；保留证书链、有效期、地址校验及 `overridePins=false`。
  账号 schema2 仍强制 WSS；历史 v1 局域网明文兼容不是账号模式的降级入口。
- 未签名的 `app-release-unsigned.apk` 仅用于确认正式变体不含测试 CA、调试网络配置和 debuggable，不作为交付 APK。
- PC 注入板端测试身份/seed 的开发模型不对 provisioning PC 保密，不代表生产安全、独立熵源或安全启动验收。
- APK 分发必须连同 [第三方声明](THIRD_PARTY_NOTICES.md) 及 `licenses/`，不要单独移除许可文件再转发。

## 2026-10-21 发布前复核

本轮只做软件和产物检查，未操作手机、板卡或公网服务。

| 项目 | 结果 |
| --- | --- |
| 核心 / 配对 / 临时 KEM / UI 状态 | 160 / 57 / 37 / 49 项断言通过 |
| HTTPS 自动配对、TLS / 接管边界 | 本机隔离测试通过，不等于真机或公网验收 |
| Gradle 8.9 离线 debug / release / vital lint | 构建成功，73 tasks；保留已有警告，不声称零警告 |
| APK v2 签名（minSDK 26） | 通过，沿用原 Debug 证书 |
| Debug CA / release 资源隔离 | 两个变体通过，无 PRIVATE KEY PEM 资源 |

可安装构建输出：`app/build/outputs/apk/debug/app-debug.apk`，4,777,751 字节。
SHA-256：`98dec91de15bb7e6158d4769efd62e0fe180ce6a3de89d07f8ba872e7d600db8`。
Debug 签名证书 SHA-256：`4d81d4c924fddebdcf83f9007586fa10a85c792fe2386592cfb566ab4ef0b81b`。

用户历史约 40–45 fps 反馈不替代 0.8 所有 UI、长稳或故障验收；全屏、旋转、不同屏宽及新版性能仍按
[0.8 真机待验清单](https://github.com/fantZach/EYEPQC/blob/v1.0.0/report/mobile_ui_20261015.md#手机待验与限制) 验证。
