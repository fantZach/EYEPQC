# 移动端子项目

## 云端 TCP 转发兼容（0.6）

现有 schema2 直接支持 `wss://<云端公网IPv4或域名>:8765/stream`，公开端口可改，例如10443；
省略端口使用443。手机访问云端的公开视频 TCP 端口，账号密码仍在 APP 输入。
采用 [云端方案](../doc/cloud_relay_plan.md) 的反向 TCP 隧道后，WSS/TLS 实际终止在 Windows PC，
账号校验、显式接管和业务二进制记录保持原样，手机继续执行 suite2/ML-KEM/GCM。
Android 沿用现有 WebSocket 路径，不增加 SSH/WebRTC 或新协议。

PC 的 TLS 叶证书 SAN 必须匹配手机 JSON 中的云端 IP/域名；只含校园网 IP 的旧证书不能用于新地址。
同一个0.6 debug测试CA为新云端地址重签叶证书后，只需可信重新导出/导入 schema2 endpoint，
只因 IP/域名或叶证书改变不必重打 APK。CA本身轮换/过期则另行更新信任；证书仍须链可信、有效期正确、SAN匹配。
板卡公钥/pin 沿用实际可信身份，改变 endpoint 不自动改变或接受新的 ML-KEM 身份。
云端配置 JSON 只含四项 version=2/endpoint/public_key_hex/public_key_sha256，不放账号密码、token或私钥。

JSON endpoint 固定为 `/stream`，不预置 takeover 查询。HTTP409仍弹出确认，只有用户确认后才请求
`/stream?takeover=1`；取消不接管，旧端4409不自动抢回。HTTP/明文WS、错误路径、URI凭据、预置查询和片段均拒绝。
debug CA只用于开发联调，release仍无测试CA；未据此标记生产、公网或Android真机通过。
本轮仅补软件测试和说明，运行时、信任资源、APK0.6未改变。见 [mobile 云端兼容记录](../report/mobile_cloud_20261014.md)。

## 0.6 debug 专用测试 CA

0.6 / versionCode6 的 debug APK 在 `src/debug` 中内置专用公开测试 CA，供本轮准备的 WSS 证书使用。
debug Manifest 只引用 debug XML，`debug-overrides` 信任该 CA，显式 `overridePins=false`，
避免 Android 的 debug CA 默认跳过未来 TLS pinning。系统 CA、证书链/有效期、SAN 主机名检查仍使用平台实现；
没有 trust-all、主机名恒真或重定向降级。schema2 WSS 与 ML-KEM 身份 pin 不变，不安装手机系统 CA，不加证书导入 UI。
debug base 显式保持原有 v1 局域网明文 WS 开发兼容；账号/schema2 不允许明文。

main/release 不引用网络配置，release 构建不包含测试 CA/调试 XML且不启用debuggable。
公开 CA 是证书，不包含 CA/server 私钥或密码；APK不自动复制到公开目录或安装。
0.5 的“仅系统信任 CA”限制在 0.6 release 仍适用，0.6 debug 额外信任这一个测试 CA。
构建/验签与资源隔离结果见 [mobile 联调前准备](../report/mobile_preboard_20261014.md)。
debug APK 4,750,025字节，SHA-256 `59e0d9a31496326ab0a3e9f4158d2a47e165eae573b8d19886b19d84f5593461`，
已验证API26 v2签名及原Debug证书。debug+release完整构建（含release vital lint）和资源隔离测试通过；
release是未签名的隔离检查产物，未安装/发布；0.6手机TLS尚未实测。
实现依据：[Android 网络安全配置](https://developer.android.com/privacy-and-security/security-config)。

## 0.5 账号与临时 KEM

新配置使用 schema2，仅四项：`version`（整数 2）、`endpoint`（`wss://.../stream`）、
`public_key_hex`、`public_key_sha256`；不包含 token、用户名、密码或私钥。8 KiB 严格解析与可信来源要求不变。
导入后输入账号密码，点击连接；每次 WSS upgrade 用 UTF-8 Basic 登录，密码只保留当前进程输入框，
禁止 view state 保存和自动填充，不写 JSON/设置/日志。TLS 用系统信任与主机名校验，不跟随重定向。
普通用户安装的自签 CA 不自动受本 APK 信任；当前请使用系统信任的 CA 签发 WSS，未提供选定 CA 导入功能。

同账号已在线的 HTTP409 弹出接管确认，只有点击“确认接管”才重连 `/stream?takeover=1`。
取消不会抢占。被接管的旧设备（4409）停流、清图并等待手动操作，不自动重连。
401/503/429 显示服务拒绝与状态码；不同账号仍只有一个观看端，不支持广播。

schema2 强制 suite2，固定身份 bootstrap 后认证临时 ML-KEM 公钥，业务密钥只来自临时 KEM。
bootstrap 不发送 START/视频；临时阶段重做双向 Finished 后才 START。拒绝 suite1 ACK、错误 TH/MAC、
重复/方向/阶段错误以及旧密钥视频。每次新连接或接管执行整套握手；每次业务会话开始设定一次 30 分钟计时，
客户端在1785秒（提前15秒）发认证 REKEY 结束旧会话并重新完成整套 suite2，为板端1800秒硬截止预留时间，
不将旧 AES REKEY 当作临时 KEM 完成。
停止、失败、关闭与离开前台取消计时并清理会话/旧图；握手各阶段 15 秒超时，失败停流。
冻结字节契约见 [suite2](../doc/account_ephemeral_protocol.md)。

version=1 的五字段 JSON 仍为显式开发兼容，界面显示“v1 开发兼容”，使用 Bearer/suite1；
账号 schema2 不会回退到此模式。系统默认 TLS 不受 v1 明文局域网开发模式影响。
已有约 40 fps 手机用户反馈属于旧开发版本，不证明 0.5 账号/suite2 的手机运行情况。
本轮证据与手机待验步骤见 [mobile 账号记录](../report/mobile_account_ephemeral_20261014.md)。
当前0.5 APK 4,772,490字节，SHA-256 `66a6c687325bbba583143f682f0f9e51057e868946fbc678d9a1990cc929c228`，
API26 v2验签及原Debug证书通过，可覆盖安装。默认测试为核心160/JSON39/临时KEM37项；
公开C fixture重放47项与真实C/WSS/JVM五窗互操作通过，未运行手机0.5。

目标：Android 手机连接 Windows PC 的局域网服务，在手机本机完成握手、认证解密与 JPEG 视频显示。
跨网可选择组网 VPN 连接 PC 与手机，或连接可选公网中转服务；VPN 供应商尚未选定，校园网可达性与吞吐须实测。
已有最小 Android 应用源码：原生 Java Activity、OkHttp 4.12.0 二进制 WebSocket、Bouncy Castle 1.81 lightweight ML-KEM-512。
最低 Android 8.0（API 26），编译/目标 API 35；不依赖系统提供 ML-KEM，不需 NDK/JNI。0.3 使用 Gson 2.11.0 严格解析单文件配对配置。
当前已通过纯 Java 离线测试并生成签名调试 APK。2026-10-13 用户报告手机正常显示视频、约 40 fps 已足够；
这是用户基础显示反馈，尚无 10 分钟窗口或手机故障恢复证据，不能标记 G8/G7 全部通过。

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
3. 安装 0.5 后，将可信 PC 生成的 `pairing.json` 传到手机，点击“导入连接配置 JSON”选择该文件。
   应用一次读取地址、令牌、800 字节公钥 hex 和 SHA-256 指纹，无需逐项填写或单独选择公钥文件。
   配置包含接入令牌，只能通过可信方式传给自己的手机，不放入公开 HTTP 下载目录。
4. 导入校验成功后显示连接地址，点击“连接”，应用执行 Encaps/Finished/START 后显示认证 JPEG；可停止、换钥和关闭。
   配置只在当前进程内存保留，不保存到应用设置；重新启动应用需再次选择 JSON。
   公钥与摘要在同一 JSON 中的匹配只能证明文件一致性，文件来源本身必须可信。
   离开前台会关闭连接；返回后需再次连接。接收队列上限 512 条、单条 1459 字节，
   组帧缓冲上限 2 MiB，界面只保留最近待显示图像；队列超限、协议/Tag/重放错误会断开并要求重新握手。
   停止、换钥及连接失败会清除待显示和已显示图像；重新认证后从首张实际显示帧开始统计平均显示 fps。

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

0.3 APK 完整构建通过（55 秒、31 tasks），单 JSON 导入 UI 已进入 APK。
调试 APK：`app/build/outputs/apk/debug/app-debug.apk`，4,742,774 字节，SHA-256：
`8d335e7d673bb57c4d5dd9bf88c7eaa8baaa06dcdc5682e39f1a012e60ce88f8`。
`apksigner verify --min-sdk-version 26` 通过 APK v2 签名验证；`aapt dump badging` 确认包名 `org.eyepqc.mobile`、
版本 0.3 / versionCode 3、最低 API 26、目标 API 35、启动 Activity 与 INTERNET 权限。
沿用初版 Android Debug 证书，可覆盖 0.1/0.2；APK 保留为本地构建产物。

0.4 APK 离线缓存构建通过（14 秒、31 tasks、10 executed），API26 v2 验签与版本检查通过。
APK 为 4,743,182 字节，SHA-256：`a217b3bb6ee9937dde6f10461347dd935919a0349b771cea6f1aaf977f81556a`；
版本 0.4 / versionCode 4，证书沿用 0.3，可覆盖安装。会话清理、SD 启动配对兼容与手机步骤见
[mobile 验证记录](../report/mobile_session_lifecycle_20261013.md)。

离线内核共 160 项断言通过（包含上述 25/20 个 KAT），另覆盖换钥后旧帧排空、新 ACK/Finished 与新视频、
HELLO 重发不耗新随机数及重复/不同 ACK 的状态约束。
JSON 导入另有 30 项解析检查。手机已显示视频为用户报告，未独立采集系统文件选择器/导入的运行证据。
真实 OkHttp/回环 WebSocket/板端 C 会话及 ML-KEM mock 的握手、视频和重连/换钥互操作见共享 `sim/tb/test_three_end.py`；
这些检查运行在 PC，未执行 Android Activity 的手机运行测试。
本轮五会话回环验证握手、重连、换钥、STOP、丢首个 ACK 重试及画面清理回调；这些均为 PC/JVM 证据。
维持用户接受的约 40 fps MVP；0.4 手机图像清除、10 分钟稳定性、断网/前后台/冷启动恢复仍需真机验证。

依赖与工具依据：[OkHttp](https://square.github.io/okhttp/)、
[ML-KEM API 源码](https://github.com/bcgit/bc-java/blob/r1rv81/core/src/main/java/org/bouncycastle/pqc/crypto/mlkem/MLKEMGenerator.java)、
[Android 命令行工具](https://developer.android.com/tools)、[AGP 版本兼容](https://developer.android.com/build/releases/about-agp)。
