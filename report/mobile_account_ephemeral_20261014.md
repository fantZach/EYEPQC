# Android 账号与临时 KEM（2026-10-14）

范围仅 mobile 源码、测试、README、本独立记录；不改共享协议/sim、板端、PC 服务或实际配置。
本轮没有硬件、ADB、SD、JTAG 或 USB CDC 操作，也不读取实际板端私钥。

## 行为与安全边界

0.5 / versionCode5 支持 schema2 四字段 version=2、WSS endpoint、800B 公钥 hex、SHA-256 pin。
不接收 token、密码、未知/重复/缺失字段或非法 UTF-8/超过8 KiB JSON。version1 明确标为开发兼容，
使用已有 Bearer/suite1；schema2 构建 suite2 Session，ACK降级直接关闭清理，无自动回退。

用户名密码输入框禁止状态保存/自动填充，凭据只用于当前进程与 WSS Basic（UTF-8），不写配置或日志。
HTTP409 显示显式接管确认；仅点击确认才发起 takeover=1 新连接。取消不抢占，4409 被接管旧端停流清图，
不自动抢回。401/503/429 保留状态码便于区分凭据、单观看端/清理失败与限速。
密码与Authorization为Java/OkHttp内部String，无法保证物理清零；本地Debug APK不是生产凭据保护验收。

TLS 使用默认系统/平台 CA 与主机名检查，禁用 HTTP/TLS 重定向；没有 trust-all、证书校验绕过或降级。
target35 默认不自动信任普通用户安装的自签CA，本轮没有选定 CA 导入功能。
部署应使用系统信任 CA 签发的 WSS（SAN匹配连接地址）；JVM测试显式装载临时公开测试CA，不代表手机可直接信任。

suite2 按冻结 `doc/account_ephemeral_protocol.md`：身份 bootstrap 双Finished后只发送HostFinished，
不发送START；type10验证bootstrap TH/HMAC后Encaps临时公钥，type11绑定整个offer；
业务TH/HKDF仅用临时KEM shared，清除bootstrap keys，再验证业务Finished并发送新HostFinished/START。
拒绝错TH/MAC、重复offer、错方向/长度/阶段、bootstrap视频及旧Finished/重放视频。
既有JPEG限制、GCM/反重放、Session清理和Activity图像释放继续复用，不增加广播/录像/后台播放。
每个业务会话设置一次定时完整重握手：`ROTATION_MILLIS=1785s`，提前15秒，为板端严格1800秒截止预留时间；
超期不继续用旧key；UI超时检查及worker记录/REKEY前检查业务deadline，到期关闭停流清图。
停止/失败/关闭/前后台断开取消定时；定时测试只缩短延时，协议不变。
新会话的临时私钥、bootstrap安全和熵源由板端提供；开发 seed 能由 PC 重建时不声明对 PC 前向保密。

## 软件验证

- `mobile/test.ps1`：旧核心160项（25 ML-KEM/20 GCM KAT）、JSON39项、新临时KEM37项通过，含本地超期停流/清理。
- `EphemeralTest <repo> board/output/account_ephemeral_fixture_20261014/fixture.json`：
  `EPHEMERAL_C_FIXTURE_OK`，总47项。公开C fixture（test_only=true）逐字节核对HELLO、身份密文、
  bootstrap HostFinished、临时reply、业务HostFinished/START，并用C业务material生成视频由Java认证接收。
  fixture是公开NIST KAT/合成coins，未使用实际私钥。
- `AccountNetworkCli` 复用原NetworkCli：key,pin,WSS endpoint,公开测试用户名,公开测试密码,JPEG sha256，
  可选rekey/stop/timer。账号构造suite2；普通`NetworkCli`保留旧suite1兼容。
  timer模式在首帧后把同一个单次Timer缩为100ms，marker `ACCOUNT_NETWORK_REKEY_OK`。
  换钥视频前及最终关闭的reset回调数量、退出超时约束继续检查。
  账号正常关闭/STOP前设100ms定时，关闭后等待250ms核对无迟到reset及无存活rotation线程，验证取消。
- `.venv/Scripts/python.exe sim/tb/test_account_three_end.py`：最终代码下五窗normal/rekey/timer/stop/normal通过，
  真实C临时KeyGen/Decaps、Python PC账号WSS、Java/OkHttp连接及认证JPEG互操作；
  两次换钥的临时公钥不同，客户端控制序列`[1,3,5,11,5,6]`，设备退出清理通过。
  TLS临时CA仅在JVM测试trustStore显式信任，USB/DMA为模拟，不是实板或手机结果。
- Gradle8.9/AGP8.7.3/JDK21/API35本地缓存构建成功，最后增量12秒、31tasks（4 executed）。
  使用已有ignored临时仓库init脚本，不持久改官方仓库。
- APK API26 v2验签、aapt包名/版本/min26/target35/启动Activity/INTERNET检查通过。
  证书SHA-256 `4d81d4c924fddebdcf83f9007586fa10a85c792fe2386592cfb566ab4ef0b81b`，沿用旧Debug证书。

本地APK：`mobile/app/build/outputs/apk/debug/app-debug.apk`，4,772,490bytes，
SHA-256 `66a6c687325bbba583143f682f0f9e51057e868946fbc678d9a1990cc929c228`。
APK是ignored构建产物，不提交仓库。

## 手机与部署待验

本轮未测0.5手机账号UI、409确认对话框、TLS信任配置、实际定时窗口、断网/后台/接管后的图像清理，
也未验完整G6 SD自主启动或真实临时KEM视频。旧版本用户约40fps反馈不自动覆盖新profile，不把G8/G7标全通过。
部署时先提供可信schema2 JSON及匹配SAN的可信WSS证书，再覆盖安装0.5、登录、正常显示、手动换钥/停止/重连。
两个设备用同账号核对409→取消不踢人→确认才接管→旧端4409且不抢回；错密码不能踢人。
真实手机记录完整换钥周期和至少10分钟显示/掉帧/停顿结果，联合PC/板端统计补门禁。
