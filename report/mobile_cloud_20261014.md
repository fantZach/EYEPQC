# Android 云端 TCP 转发兼容（2026-10-14）

先完整读取 `doc/cloud_relay_plan.md`、Ponytail skill；仓库检索未发现 AGENTS.md。
冻结方案是四端分工：Board USB、PC现有WSS、Server反向TCP转发、Android现有账号/suite2。
本聊天只改 mobile 测试/README及本报告。按协调者后续要求不stage/commit，由主聊天最终统一提交。

## 兼容结论

无须修改Android运行时：PairingConfig schema2已有公网IPv4/域名WSS与自定义端口；
StreamClient已有Basic账号、/stream、用户明确选择后的takeover=1、HTTP409确认回调、4409停流及suite2。
MainActivity仍仅在接管确认的positive按钮调用connect(true)。没有新运行时抽象/SSH/WebRTC/板端协议。
保持0.6/code6、debug测试CA/overridePins=false、系统CA/主机名验证、ML-KEM身份pin与旧局域网兼容。

手机使用云端公开TCP视频端口（默认8765，可自定义；省略端口443），TLS实际终止PC。
PC叶证书SAN要匹配云端地址；原仅校园网SAN证书不会因隧道而自动有效。
同一0.6 debug CA为新云端地址重签叶证书不需要为IP变化重打APK；更新可信schema2 endpoint即可。
CA轮换/过期须另外更新信任；endpoint改变不自动更新ML-KEM pin。不把debug信任当生产状态。
JSON不预置takeover查询、不携带账号密码/SSH密钥；实际用户确认后才追加takeover=1。

## 定向软件验证

1. `mobile/test.ps1 -Jdk C:/Users/23976/AppData/Local/Programs/STM32CubeMX/jre`：
   `ANDROID_CORE_OK checks=160 MLKEM_KAT=25 GCM_KAT=20`；JSON增至52项，`EPHEMERAL_OK checks=37`。
   JSON新增3个正例：公网文档IPv4端口8765、域名端口10443、域名默认443。
   新增10个拒绝例：HTTP/HTTPS非WebSocket、公网明文WS、0/65536端口、错误路径、
   预置takeover/token查询、URI用户名密码和fragment。正例只做解析，不联系公网。
2. `.venv/Scripts/python.exe mobile/test/test_cloud_endpoint.py`：四个回环TLS/HTTP场景通过，
   使用真实StreamClient/OkHttp、一次性127.0.0.1 TLS监听器、随机自定义端口、合成自签证书和公开测试凭据：
   - 未信任证书：连接失败并清理；服务器未收到HTTP/Basic请求。
   - JVM显式信任测试证书但SAN为wrong.example、连接localhost：主机名错误拒绝并清理，无HTTP请求。
   - SAN=localhost且JVM显式信任：请求仅GET /stream，HTTP409产生一次接管确认回调，不自动发送takeover。
   - 测试调用明确传takeover=true：请求GET /stream?takeover=1，HTTP503关闭/清理且无接管提示。
   合成私钥仅为本测试生成/使用，随临时目录删除；未读取实际tmp/private或真实账号/证书私钥。
   JVMtrustStore仅测试进程使用，没有修改Android/app默认TLS策略、系统信任或现有代理/服务。

复用已有Java/OkHttp与Python cryptography依赖，不增加依赖或打包测试CLI。
新增CloudEndpointCli位于mobile/test，只构造公开全零800B身份做失败路径；没有完成板端握手或解密视频。

## 文件与边界

本轮文件：`mobile/test/org/eyepqc/mobile/PairingConfigTest.java`、
`mobile/test/org/eyepqc/mobile/CloudEndpointCli.java`、`mobile/test/test_cloud_endpoint.py`、
`mobile/README.md`、`report/mobile_cloud_20261014.md`。
不修改mobile/app运行时/证书/构建版本，不重建或更新APK；不改pc/server/board/共享doc、P2P原型。
原四项pre-commit hook保持，由主聊天最终提交时运行；本聊天额外执行同一hook作软件检查。
未部署/操作真实服务、代理、云账户或SSH隧道，未安装手机、操作硬件/JTAG/SD。

本轮不是Android真机TLS/UI、公网IPv4/域名可达性、实际隧道、吞吐/视频或G9验收。
后续部署仍需匹配SAN的真实叶证书、账号、服务器受限隧道与主机key核验，以及手机实际连接/视频/故障恢复记录。
