# Android 部署、升级与用户验收

当前候选：`0.9.0-rc1` / versionCode 9，包名 `org.eyepqc.mobile`，Android 8.0/API 26 及以上。
本轮交付软件与构建路径；验收由用户统一执行。`release` 表示非调试构建，不表示生产密钥安全已经验收。

## 1. 选择正确的 APK

| 文件/模式 | 用途与限制 |
|---|---|
| `debug` APK | 沿用已有 Debug 签名，可覆盖原调试版；仅系统 CA + 原专用测试 CA。测试 CA 在 2026-11-12 16:59:03 UTC 到期，不能用于长期部署。 |
| `release-unsigned` APK | 已禁用 debuggable、明文流量，默认只信系统 CA；**未签名，不能安装**。缺少正式签名材料时只交付此候选，不能改名冒充已签名版。 |
| 外部密钥签名的 `release` APK | 使用操作者管理的签名密钥，可在同签名下升级；部署到自有 CA 时必须显式输入其公开证书，不能默认继承旧测试 CA。 |

正式 APK 不内置默认公网 IP。首次打开会展开“连接设置”，输入部署者提供的可信地址。
调试版保留 `wss://124.70.38.245:8765/stream` 作为历史开发入口，不承诺此服务长期可用。
`release` 不支持旧明文 WS；账号模式始终要求 WSS，不能因证书失败退回 WS。

## 2. 构建前提

准备 JDK 17+、Gradle 8.9、Android SDK Platform 35 与 Build Tools 35.0.0，首次按可信官方来源安装工具和依赖。
在仓库根目录设置本次进程参数，不修改系统代理或永久环境变量：

```powershell
$jdk='C:/path/to/jdk'
$sdk='C:/path/to/android-sdk'
$gradle='C:/path/to/gradle-8.9/bin/gradle.bat'
& ./mobile/test.ps1 -Jdk $jdk
& ./mobile/build.ps1 -Jdk $jdk -Sdk $sdk -Gradle $gradle -Variant Debug
& ./mobile/build.ps1 -Jdk $jdk -Sdk $sdk -Gradle $gradle -Variant Release
```

`-Offline` 只适用于依赖已完整缓存的机器；缺依赖时应补齐可信缓存，不能关闭 lint 或校验。
`-InitScript` 仅接受操作者已检查的本地 Gradle init 脚本；该脚本可执行代码，不使用来源不明脚本。
现有本机历史缓存使用官方 `dl-ssl.google.com` 的仓库映射，不等于通用部署前提。
需要归档时使用 `-OutputDirectory 'D:/deliver/android-rc1-new'`，父目录须已存在、目标目录须不存在；
导出 APK 与非秘密 `manifest.json`，包含哈希、签名状态、信任类型与 `user_acceptance=pending`。

## 3. 无域名/IP WSS 的专用 CA

目前使用服务器 IP `124.70.38.245`。公网链路仍是手机 → 云端透明 TCP → PC；**TLS 叶证书私钥在 PC**，云端不终止业务 TLS。
不能把 IP 地址当作 DNS SAN：PC 叶证书必须含 `IP:124.70.38.245`，并具有有效服务端用途、有效期及完整证书链。
叶证书可能早于 CA 到期；必须检查当前部署文件的 `notAfter`，不能仅看上述测试 CA 的到期日期推断服务仍有效或已经过期。
新的 PC TLS 准备工具会分别记录 `ca_expires_utc` 与 `leaf_expires_utc`，更新前先核对两者。

对于自有 CA，由操作者按 [PC 部署教程](https://github.com/fantZach/EYEPQC/blob/main/pc/DEPLOYMENT.md) 在受保护位置管理 CA 私钥和 PC 叶证书私钥，手机只需要 CA 的**公开 PEM**。
PC 准备工具的公开 CA 路径为新输出目录下 `public/ca.pem`；以下以 `D:/eyepqc-secure/tls-new/public/ca.pem` 为例。
通过独立可信渠道核对该 CA 的 SHA-256 指纹（例如 `openssl x509 -in deployment-ca.pem -noout -fingerprint -sha256`）。
APK 签名密钥与 TLS CA 是两套不同密钥，不可混用；不要把任何私钥发送到聊天、Git 或 APK。

```powershell
& ./mobile/build.ps1 -Jdk $jdk -Sdk $sdk -Gradle $gradle -Variant Release `
  -TrustCaFile 'D:/eyepqc-secure/tls-new/public/ca.pem'
```

显式 CA 构建会把这一张公开 CA 加入 release 的系统信任锚，**属于该部署的信任根变更**。
不是 debug-overrides，不会信任其他用户安装的 CA，也不会关闭证书链、期限、IP/域名校验或设置 `overridePins=true`。
输入只允许单张当前有效、允许签发证书的公开 CA；拒绝私钥/多证书/过期证书/普通叶证书，以及原 debug CA。
省略参数时恢复系统 CA-only，先前生成的自有 CA 不会残留进入默认 APK。

CA 轮换必须提前发放含新信任根的已签名 APK，并与 PC 证书部署协调；本轮不自动替换正在使用的证书。
叶证书可在同一受信 CA 下正常续期，但 IP/域名须保持匹配；CA 到期或换根需要重新构建并发布。

## 4. 正式签名（本轮不自动创建密钥）

由维护者建立独立受保护的 Android 发布 keystore；可使用 JDK 的 `keytool -genkeypair` 交互创建，密码在工具提示中输入。
先按 PC 教程准备仅当前用户/SYSTEM 可访问的私有目录，确认目标文件不存在；首次创建示例：

```powershell
if(Test-Path 'D:/eyepqc-secure/private/android-release.jks'){throw 'Keystore already exists; do not replace it.'}
& "$jdk/bin/keytool.exe" -genkeypair -alias eyepqc-release -keyalg RSA -keysize 3072 `
  -validity 3650 -storetype PKCS12 -keystore 'D:/eyepqc-secure/private/android-release.jks'
```

备份 keystore、别名、密码恢复信息及签名证书指纹到离线受保护介质；丢失签名密钥通常无法给已有安装做同签名升级。
不可用 `CN=Android Debug` 的密钥冒充正式签名，构建脚本会拒绝导出。

脚本只通过以下进程环境变量读取签名设置，不接受密码命令行参数或仓库内密码文件：

```powershell
$env:EYEPQC_ANDROID_KEYSTORE='D:/eyepqc-secure/private/android-release.jks'
$env:EYEPQC_ANDROID_KEY_ALIAS='eyepqc-release'
try {
    $storeSecret=Read-Host 'Keystore password' -AsSecureString
    $keySecret=Read-Host 'Key password' -AsSecureString
    $env:EYEPQC_ANDROID_STORE_PASSWORD=[Net.NetworkCredential]::new('', $storeSecret).Password
    $env:EYEPQC_ANDROID_KEY_PASSWORD=[Net.NetworkCredential]::new('', $keySecret).Password
    & ./mobile/build.ps1 -Jdk $jdk -Sdk $sdk -Gradle $gradle -Variant Release -RequireSigned `
      -TrustCaFile 'D:/eyepqc-secure/tls-new/public/ca.pem' `
      -OutputDirectory 'D:/deliver/android-signed-rc1-new'
} finally {
    'EYEPQC_ANDROID_KEYSTORE','EYEPQC_ANDROID_KEY_ALIAS','EYEPQC_ANDROID_STORE_PASSWORD','EYEPQC_ANDROID_KEY_PASSWORD' |
      ForEach-Object { Remove-Item "Env:$_" -ErrorAction SilentlyContinue }
    $storeSecret=$null; $keySecret=$null
}
```

环境变量在构建进程中是明文，须在可信单用户机器上执行，不开 Gradle `--debug`/构建扫描，不把环境转储到日志。
四项须同时给出，否则拒绝构建；`-RequireSigned` 缺材料直接失败，不回退 Debug key。
输出会经 SDK `apksigner verify --min-sdk-version 26 --print-certs` 验签，记录公开签名证书 SHA256，不输出密码。

## 5. 安装、登录与身份确认

1. 从可信交付位置取得 APK、部署说明、NOTICE/许可证和 SHA256，先核对哈希与签名证书指纹。
2. 已装调试版时，正式版签名一般不同，Android 会拒绝覆盖。先记下可信 WSS 地址及板端公钥指纹/公开配对文件；
   在确认新包来源后手动卸载旧包，再安装正式包。此操作清除 APP 私有配置，不改变 PC 的账号或板端身份。
3. 初次打开“连接设置”，输入 `wss://124.70.38.245:8765/stream`（或实际可信地址）。只向确认归属且证书有效的端点输入账号密码。
4. 输入 PC 管理员创建的用户名/密码，点“连接并观看”。应用经同源 HTTPS 获取公开 schema2，之后执行 WSS、ML-KEM、Finished、视频验 Tag。
5. 首次身份信任来自已验证的 TLS 源。需要独立身份确认时，先核对管理员提供的公开板端指纹，或可信手动导入公开 JSON；不导入密码、token 或私钥。
6. 已记住身份后，同地址板端公钥变化会被拒绝。不要盲目清应用数据；先向管理员核对原因和新指纹，再可信手动导入。
7. 同账号另一设备已观看时，会提示显式接管；只有确认后才关闭旧设备会话。不同用户名不绕过板卡单观看能力。

换服务器时先停止观看，核对新端点、TLS SAN/CA 和公开板端身份；不要通过关闭 TLS 或删除 pin 来迁移。
密码只在当前进程使用，不写入配对/偏好设置；不要把它放进 URL、截图、日志或聊天。
离开前台即断开并清除画面；不提供后台播放、自动接管或隐藏重连。

## 6. 升级、回滚与故障定位

- 同包名、同签名且较高 versionCode 可正常升级，公开配对配置保留。先记录当前包版本/哈希/签名指纹。
- 不同签名不能直接覆盖；不要去关闭 Android 签名校验。卸载重装会丢失本机配对设置，需再次可信确认。
- Android 默认拒绝降 versionCode。回滚应发布使用原签名但递增 code 的修复包；强行卸载旧版重装由操作者明确决定。
- “TLS 证书校验失败”：查手机时间、叶证书 SAN/期限、完整链、当前构建的 CA。自动配对发生在板端握手之前，此错误不是 ML-KEM 或 USB 故障。
- “账号或密码错误 / HTTP 401”：在 PC 用账号命令核对/修改密码，并正常重启 relay 加载数据库快照；不反复尝试猜密码。
- “网络连接超时”：先检查 PC 服务、受限 SSH 隧道、云端端口与网络；不要直接重刷板卡。
- “握手超时 / 认证或协议失败”：保留不含秘密的状态和时间，按 PC/板端诊断定位；已知首次 USB QUERY 故障仍待用户统一验收，不靠手机无限重试掩盖。
- 帧率偏低：同时记录 APP 认证帧/显示 FPS、PC USB/网络计数和板端公开计数，分清显示和上游吞吐，不仅依据 UI FPS 认定根因。

## 7. 用户统一验收记录

记录 APK/签名/CA 指纹、PC/Board/Server 版本、手机型号/系统、时间和各项结果；不要记录密码或密钥。
至少覆盖首次登录、错密码、错误/过期/错 SAN 证书拒绝、首次 pin 与身份变化拒绝、首连/STOP/重连、
手动与 30 分钟换钥、同账号显式接管、前后台、全屏/旋转、稳定帧率及网络/USB故障。
软件测试与构建结果不能替代这些手机/板卡结果；正式发布需要你给出统一验收结论。
