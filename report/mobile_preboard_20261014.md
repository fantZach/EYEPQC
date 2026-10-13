# Android 联调前准备：debug 专用测试 CA（2026-10-14）

用户授权将 PC 生成的专用公开测试 CA 内置 debug APK，不修改手机系统信任，不添加证书导入 UI。
仅修改 mobile 及本独立报告，不操作服务、硬件、JTAG、SD、USB CDC 或手机安装。

## 最小变更与信任范围

- `mobile/app/src/debug/res/raw/eyepqc_test_ca.pem`：仅一个公开 X.509 CA 证书，
  来自 `tmp/preboard_20261014_r1/public/ca.pem`。复制前独立核对 PC 提供的 DER SHA-256 指纹，
  确认 BasicConstraints CA=true。未读取或复制 private 目录、CA/server 私钥、账号文件或密码。
- debug Manifest 引用 `@xml/eyepqc_debug_network_security`；debug XML 的 base 仅信任系统 CA，
  debug-overrides 额外信任上述 CA，并显式 `overridePins=false`。
  Android 在 debug-overrides 内的默认 overridePins 为 true，本次显式设 false，避免以后 TLS pinning 被自动绕过。
  依据：[Android 网络安全配置](https://developer.android.com/privacy-and-security/security-config)。
- 原 OkHttp 默认证书链/有效期/SAN 主机名检查不变，没有 trust-all、主机名恒真或自定义 TrustManager。
  schema2 必须 WSS，ML-KEM 身份 pin 与 suite2 不变。保留禁用重定向。
- debug base 明确保留原 `cleartextTrafficPermitted=true`，用于已有显式 v1 局域 WS 开发兼容；
  加入 NSC 后若不明确设置，target35 的默认值会禁用旧开发路径。schema2/Basic 不允许明文。
- main/release 源码没有测试 CA/网络配置引用；release 不包含它们、不启用 debuggable。
  release 继续只信任系统 CA。本测试 CA 只影响当前 app 的 debug 信任，不安装到系统。

## CA 与 APK

CA DER SHA-256：`263c8c06420a2b72726d93c746766d3efd8040fe6d711af49f240ebbc1b4dc8b`。
CA 有效期（北京时间）：2026-10-14 00:54:03 至 2026-11-13 00:59:03。
PC 公共服务器链/SAN 与服务部署由 PC 聊天负责；本轮未启动服务做实际 Android TLS 连接。

debug APK：`mobile/app/build/outputs/apk/debug/app-debug.apk`，0.6 / versionCode6，4,750,025 bytes。
SHA-256：`59e0d9a31496326ab0a3e9f4158d2a47e165eae573b8d19886b19d84f5593461`。
`apksigner verify --verbose --print-certs --min-sdk-version 26`：v2 验签通过，
Android Debug 证书 SHA-256 `4d81d4c924fddebdcf83f9007586fa10a85c792fe2386592cfb566ab4ef0b81b`，
与旧版相同，可覆盖安装；aapt 确认包名、版本、min26/target35、启动 Activity 和 INTERNET。

release 隔离检查产物：`mobile/app/build/outputs/apk/release/app-release-unsigned.apk`，4,145,490 bytes。
SHA-256：`7ccc3f425b701d7dd15bfc4889dd928ebc5298dd4f19e65bb9abb0ae3dd931dc`。
这是未配置正式签名的 unsigned 验证产物，不是可安装或已签名发布 APK。
两个 APK 都保留为 ignored 本地产物，不提交、不自动公开复制或安装。

## 验证

- `mobile/test.ps1`：核心160 / JSON39 / 临时 KEM37 项通过，未改变协议或握手逻辑。
- Gradle8.9/AGP8.7.3/JDK21：`:app:assembleDebug :app:assembleRelease` 完整成功，
  最后构建55秒、73 tasks（3 executed），含 `lintVitalAnalyzeRelease`、`lintVitalReportRelease`、`lintVitalRelease`。
  首次 offline release 因 lint-gradle31.7.3 缓存缺失失败；后续通过已有临时官方 CDN init 脚本及当前命令的
  本机代理参数补齐缓存，不关闭 lint，不持久修改项目/系统代理。SDK远程清单仍有TLS警告，但成功构建使用已安装API35。
- `mobile/test/check_debug_ca.py` 源码与最终 APK 检查：debug/release 均 `DEBUG_CA_ISOLATION_OK`，
  证书指纹与独立 PC 值匹配。检查源与产物无 PRIVATE KEY PEM、主/release无测试引用、
  debug raw PEM 与源证书字节一致、compiled XML保留debug-overrides和overridePins=false；
  release 压缩包无CA/调试XML/证书PEM或DER，compiled Manifest 无networkSecurityConfig或debuggable属性。

复现隔离检查（仓库根目录）：

```powershell
./.venv/Scripts/python.exe mobile/test/check_debug_ca.py . build/mobile_toolchain/sdk/build-tools/35.0.0/aapt.exe 263c8c06420a2b72726d93c746766d3efd8040fe6d711af49f240ebbc1b4dc8b
```

本轮仅验证构建、签名、指纹和资源隔离，没有手机TLS/账号UI/视频、实板或服务运行结果。
测试 CA 签发权限只用于 debug 联调，不能作为生产 trust anchor；正式版不携带它。
后续须以实际手机连接匹配SAN且未过期的测试服务器链，验证正常登录和错误主机名/不可信证书拒绝。
