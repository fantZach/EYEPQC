# 移动端子项目

目标：Android 手机连接 Windows PC 的局域网服务，在手机本机完成握手、认证解密与 JPEG 视频显示。
跨网可选择组网 VPN 连接 PC 与手机，或连接可选公网中转服务；VPN 供应商尚未选定，校园网可达性与吞吐须实测。
已有最小 Android 应用源码：原生 Java Activity、OkHttp 4.12.0 二进制 WebSocket、Bouncy Castle 1.81 lightweight ML-KEM-512。
最低 Android 8.0（API 26），编译/目标 API 35；不依赖系统提供 ML-KEM，不需 NDK/JNI。0.3 使用 Gson 2.11.0 严格解析单文件配对配置。
当前已通过纯 Java 离线测试并生成签名调试 APK，**手机/板卡实测仍待完成**。

## 必须实现的功能

- 通过可信配置取得板卡 ML-KEM-512 公钥并固定校验其指纹，不能无条件信任转发服务临时下发的公钥。
- 使用移动端可靠随机源执行 Encaps，与板卡完成 HKDF、双向 Finished，再发送认证 START。
- 按 [共享协议](../doc/protocol.md) 解析视频记录，校验 session、序号、AAD 与 AES-GCM Tag。
- 完整帧的所有分片通过认证后才交给 JPEG 解码器，限制帧长、分片数和缓存，丢弃缺片或认证失败的帧。
- 展示连接状态、认证帧率和丢帧；提供停止和换钥，断线时销毁会话并重新握手。
- Android 应用声明网络访问权限；网络收发、密码运算与 JPEG 解码在后台线程执行，界面线程负责显示。
- 提供显式关闭连接；应用退出或连接失败时清理会话、缓存及网络资源，重连必须重新握手。

第一版为前台运行的 Android 应用，面向一块板、一个观看端、实时 JPEG 显示；录像、后台服务和多观看端不列入 MVP。
不向 PC 或中转服务器发送业务 AES 密钥、ML-KEM 封装随机数或共享秘密。

网络适配沿用 [三端架构](../doc/architecture.md)：二进制 WebSocket 每个消息承载一条完整 USB 记录，
控制双向、视频仅板端到手机。限制消息长度与缓存；队列超限时关闭连接并重新握手，具体板端会话复位由 PC 执行。
公网使用 WSS；局域网或组网 VPN 的连通性不替代观看接入授权及内层密码认证。

## 复用与验证依据

以 `../pc/src/host/protocol.py`、`handshake.py`、`receiver.py` 和 `g6_board.py` 为互操作参考，
以 `../data/kat/`、`../sim/vectors/` 为公开测试向量。Python 参考代码不等于移动端运行实现；
ML-KEM 使用 Bouncy Castle lightweight API；HKDF-SHA-256、Finished/控制 HMAC 和 AES-GCM 使用标准 Java 密码接口，
实际握手使用 `SecureRandom`；固定种子仅用于公开测试向量。避免替换 Android 全局密码 provider。

先完成协议/KDF/KEM/GCM 向量与篡改/重放测试，再接局域网真实板卡。
验收记录必须分别给出板端采集帧率、网络收包率、手机认证解码显示帧率和延迟；不得照搬 PC 的约 47 fps。
任务顺序与门禁见 [steps 第 22 节](../doc/steps.md#22-三端扩展pc-转发与移动端解密)。

当前 JTAG 测试私钥由 PC 装载，尚不能验证对该 provisioning PC 保密的生产级安全模型。
安全边界见 [三端架构](../doc/architecture.md)。

## 构建与使用

1. 准备 JDK 17+、Gradle 8.9、Android SDK `platforms;android-35` 和 `build-tools;35.0.0`。
2. 在仓库根目录构建：

   ```powershell
   ./mobile/build.ps1 -Jdk 'C:/path/to/jdk' -Sdk 'C:/path/to/android-sdk' -Gradle 'C:/path/to/gradle-8.9/bin/gradle.bat'
   ```

   输出为 `mobile/app/build/outputs/apk/debug/app-debug.apk`。调试 APK 供开发验证，不代表发布版本。
3. 安装 0.3 后，将可信 PC 生成的 `pairing.json` 传到手机，点击“导入连接配置 JSON”选择该文件。
   应用一次读取地址、令牌、800 字节公钥 hex 和 SHA-256 指纹，无需逐项填写或单独选择公钥文件。
   配置包含接入令牌，只能通过可信方式传给自己的手机，不放入公开 HTTP 下载目录。
4. 导入校验成功后显示连接地址，点击“连接”，应用执行 Encaps/Finished/START 后显示认证 JPEG；可停止、换钥和关闭。
   配置只在当前进程内存保留，不保存到应用设置；重新启动应用需再次选择 JSON。
   公钥与摘要在同一 JSON 中的匹配只能证明文件一致性，文件来源本身必须可信。
   离开前台会关闭连接；返回后需再次连接。接收队列上限 512 条、单条 1459 字节，
   组帧缓冲上限 2 MiB，界面只保留最近待显示图像；队列超限、协议/Tag/重放错误会断开并要求重新握手。

## 单文件配置格式

JSON 版本为 1，固定五个字段：`version`（整数 1）、`endpoint`、`token`、`public_key_hex`、`public_key_sha256`。
公钥使用 1600 位 ASCII hex，指纹 64 位 hex；令牌为 32～256 个非空格可打印 ASCII 字符。
最大文件 8 KiB，严格 UTF-8/JSON，拒绝重复/缺失/未知字段、尾随内容、格式错误和摘要不一致。
公网地址使用 WSS；明文 WS 只允许显式局域网/回环/VPN 数字地址。
PC 导出命令见 [配对工具](../pc/README.md)，首次导入后点击连接，导入本身不自动发起网络请求。
   显式换钥时，在新 HELLO_ACK 到来前排空旧会话的完整视频记录，不显示、不计入认证帧；普通握手前视频仍拒绝。
   等待 HELLO_ACK 时每隔 3 秒原样重发 HELLO，最多 2 次；不生成新随机数或延长 15 秒握手期限。
   仅在等待 Finished 阶段忽略逐字节相同的缓存 HELLO_ACK；不同 ACK、其他状态和认证失败仍拒绝。

应用禁止截图/备份，不写密钥、令牌或 JPEG 明文日志。Java/密码库内部副本不保证物理清零，
资源释放采用可控数组尽力覆盖；该开发 MVP 不包含生产熵源、板端安全存储或启动保护验收。
OkHttp 会先接收完整网络消息再调用应用，1459 字节检查属于应用边界；不能声称已限制库内任意恶意大消息的瞬时分配。

## 离线校验

```powershell
# 首次从 Maven Central 获取固定依赖并核对 SHA-256；缓存位于 ignored build/mobile_toolchain。
./mobile/test.ps1 -Jdk 'C:/path/to/jdk' -FetchDependencies
# 缓存齐全后，无需联网。
./mobile/test.ps1 -Jdk 'C:/path/to/jdk'
```

`CoreTest` 覆盖 25 个公开 NIST ML-KEM Encaps KAT、20 个 NIST AES-GCM KAT，
以及固定 KDF/Finished/控制 MAC、篡改/重放、组帧/缺片/字段不一致、STOP/REKEY 和传输地址边界。
`ClientCli` 供共享测试驱动，参数为公钥文件和可信 pin，stdin 支持 `START`、`RECEIVE <完整USB记录hex>`、
`STOP`、`REKEY`、`CLOSE`；stdout 的 `SEND`/`FRAME` 使用公开 fixture，`READY` 表示本条命令处理完成。
`NetworkCli` 用实际 OkHttp 验证公开 JPEG fixture 的认证接收与 SHA-256，不输出图像内容；这些 CLI 不打包到 APK。
`LiveProbe` 用同一客户端接实际 PC 桥，参数为公钥路径、pin、端点、令牌文件、输出目录、秒数；
ImageIO 独立解码并保存首/末 JPEG 与结果 JSON，不把令牌放入进程参数。首认证帧后起计时，
要求认证解码跨度达到目标窗口的 90% 且没有超过 5 秒帧间停顿；JVM 的测得帧率不代表 Android 手机显示帧率。

2026-10-13 本机 JDK 21、Gradle 8.9、AGP 8.7.3、Platform 35 rev 2、Build Tools 35.0.0 完整构建成功，
初版 31 项 Gradle 任务执行，构建耗时 2 分 28 秒；修正版 0.2 缓存构建耗时 25 秒（10 执行、21 已是最新）。官方主下载地址曾 TLS 失败，后通过已有本地代理和官方
`dl-ssl.google.com`/Google CDN 取得工具与依赖；工具缓存与临时仓库 init 脚本位于 ignored 目录，未修改系统代理。

当前 0.3 APK 完整构建通过（55 秒、31 tasks），单 JSON 导入 UI 已进入 APK。
调试 APK：`app/build/outputs/apk/debug/app-debug.apk`，4,742,774 字节，SHA-256：
`8d335e7d673bb57c4d5dd9bf88c7eaa8baaa06dcdc5682e39f1a012e60ce88f8`。
`apksigner verify --min-sdk-version 26` 通过 APK v2 签名验证；`aapt dump badging` 确认包名 `org.eyepqc.mobile`、
版本 0.3 / versionCode 3、最低 API 26、目标 API 35、启动 Activity 与 INTERNET 权限。
沿用初版 Android Debug 证书，可覆盖 0.1/0.2；APK 保留为本地构建产物。

离线内核共 158 项断言通过（包含上述 25/20 个 KAT），另覆盖换钥后旧帧排空、新 ACK/Finished 与新视频、
HELLO 重发不耗新随机数及重复/不同 ACK 的状态约束。
JSON 导入另有 30 项解析检查，PC 当前实际配置的跨语言解析也通过；手机系统文件选择器/导入运行仍待真机验证。
真实 OkHttp/回环 WebSocket/板端 C 会话及 ML-KEM mock 的握手、视频和重连/换钥互操作见共享 `sim/tb/test_three_end.py`；
这些检查运行在 PC，未执行 Android Activity 的手机运行测试。
手机安装修正版后实际认证显示、校园网/VPN 连通、完整板端异常恢复和手机显示 45 fps 门禁仍需实测。

依赖与工具依据：[OkHttp](https://square.github.io/okhttp/)、
[ML-KEM API 源码](https://github.com/bcgit/bc-java/blob/r1rv81/core/src/main/java/org/bouncycastle/pqc/crypto/mlkem/MLKEMGenerator.java)、
[Android 命令行工具](https://developer.android.com/tools)、[AGP 版本兼容](https://developer.android.com/build/releases/about-agp)。
