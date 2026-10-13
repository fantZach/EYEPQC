# 上板前准备完成：debug CA / WSS / 账号 / APK

此记录仅说明准备就绪，不代表上板或手机验收通过。未下载固件、写SD、调整启动拨码或启动正式8765服务。

## 已准备文件

公共移交目录 `tmp/preboard_20261014_r1/public/`：

- `EYEPQC-0.6-debug.apk`：可覆盖安装旧调试版，4,750,025字节，SHA256
  `59e0d9a31496326ab0a3e9f4158d2a47e165eae573b8d19886b19d84f5593461`。
- `pairing.json`：schema2四项，无token/密码，endpoint=`wss://10.179.236.247:8765/stream`。
- `EYEPQC-preboard-0.6.zip`：只包含上述APK与JSON，没有账号文件、密码或私钥。
- `ca.pem` / `server-chain.pem`：公开证书，不是密钥。

私有目录 `tmp/preboard_20261014_r1/private/`：
`ca-key.pem`、`server-key.pem`、`accounts.json`、`login.txt`。Windows ACL限制当前用户与SYSTEM；
用户名viewer，随机强密码仅本机login.txt供操作者读取，不在聊天/日志/参数/JSON/APK/Git中出现。
公共下载只能服务public目录，不能服务含private的父目录。此轮没有启动下载服务。

## 独立复核

- PC物理以太网地址为10.179.236.247，不使用Mihomo 198.18.0.1。
- CA DER SHA256 `263c8c06420a2b72726d93c746766d3efd8040fe6d711af49f240ebbc1b4dc8b`；
  leaf DER SHA256 `b14a17a80477fd00a4a1b120d714e7fc38fa6cfeda37eae03fc08292e4bebbf3`。
- leaf SAN为10.179.236.247、127.0.0.1、localhost；serverAuth用途，CA30天、leaf7天。
  leaf截至北京时间2026-10-21 00:59:03，CA截至2026-11-13 00:59:03；IP改变需重签叶证书。
- 板卡公开身份沿用并比对现有800字节公钥，pin=`a14a7f6fe9e862b90e66e413e4d0fcdbfc63e1b8bc0c0ff31e11324482927928`。
  没有读取板卡私钥或做provisioning。
- debug CA仅在src/debug，overridePins=false；协调者独立运行源/APK隔离检查，两variant均通过。
  release unsigned产物不含CA/调试XML/NSC/debuggable；它只是隔离验证产物，不用于手机安装。
- TLS链/有效期/地址校验、schema2强制WSS与ML-KEM身份校验保留；原v1局域WS仅作显式开发兼容。
- PC准备工具2项离线测试覆盖证书用途/期限/CA复用、覆盖拒绝、Windows ACL及失败前置，未向真实服务发请求。
- PC另用本轮真实材料在127.0.0.1临时端口与mock CDC验证WSS账号成功、错密码401、错CA/hostname拒绝，结束后关闭listener。
  不是正式8765、真实USB或手机验收。证据见 [PC报告](preboard_pc_20261014.md)。
- Android核心160/JSON39/临时KEM37、debug+release完整构建（含lint）、v2验签/旧签名匹配通过。
  详情见 [Mobile报告](mobile_preboard_20261014.md)。
- 最终ARM固件 `build/vitis/g6_account_ephemeral_20261014_2` 再次完整预检通过75哈希/BSP lookup/startup；未上板。

## 操作者下一步

将公共ZIP中的0.6调试APK与pairing.json复制到手机，覆盖安装、导入JSON；
密码只在电脑本机login.txt查看，稍后手机登录时输入。不安装CA到系统，不安装release unsigned APK。
接好OV5640、JTAG、USB Slave、调试串口和电源，保持现有SD/拨码，等明确授权后临时装载视频固件。
实际WSS启动命令已保存于PC报告，待上板准备好后再启动；目前手机连接失败不代表密码或固件错误，因为正式服务未运行。

测试CA密钥泄露需换CA并重打调试APK；IP改变而保持同一CA只需新leaf与JSON，复用工具的新输出目录会新建测试账号，勿误用旧密码。
本阶段仍是开发测试，不能宣称生产熵/长期身份安全保存、完整G6视频SD启动或手机新profile性能通过。
