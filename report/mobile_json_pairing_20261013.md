# Android 单 JSON 配对（2026-10-13）

用户要求简化参数与文件填写。0.3 移除三个手填框和单独公钥选择，改成系统文件选择器导入一个 JSON，
一次读取地址、token、800 字节公钥 hex 与指纹；校验后显示地址，点击连接使用同一套 Session/StreamClient。
导入本身不自动连接；配置留在进程内存，不写应用设置，退出进程后可重新选择原 JSON。

配置格式固定五项：version=1（整数）、endpoint、token、public_key_hex、public_key_sha256。
使用已有 Gson 2.11.0 的严格 JsonReader，拒绝重复/缺失/未知字段、错误类型、尾随内容、不合法 UTF-8、
超过 8 KiB、错误 URL/端口/令牌、公钥长度/hex 或 SHA-256 不一致。绑定摘要是文件一致性检查，不能代替可信配置来源。

PC `prepare_pairing.py` 新生成配对目录同时产生私有 `pairing.json`；已有服务可用
`--token-file ... --config-file ...` 导出而不轮换运行中 token，拒绝覆盖文件。
本轮实际生成 `tmp/mobile_pairing/pairing.json`，Android 解析器验证通过（31 项，含实际配置）。
配置含接入凭据，不进入 public/，不提交 Git；新增默认 pairing.json 忽略和审阅包硬排除。
不读取/导出板端私钥。用户只需可信传送该 JSON，不需要分别传公钥或手输长指纹/token。

验证：Android 原有 158 项检查通过；JSON 解析 30 项检查通过（加实际 PC 生成配置为 31 项）；
PC 配对工具 7 项测试通过。APK Gradle 正式构建通过（55 秒、31 tasks、13 executed），API26 v2 验签和版本检查通过。
版本 0.3 / versionCode3，沿用旧 Android Debug 证书。
APK 4,742,774 字节，SHA-256：`8d335e7d673bb57c4d5dd9bf88c7eaa8baaa06dcdc5682e39f1a012e60ce88f8`。
下载副本为 `tmp/mobile_pairing/public/EYEPQC-0.3.apk`；JSON 刻意留在私有父目录，不暴露给未认证 HTTP 下载。

本轮未通过 ADB 操作手机，也未验证手机文件选择器或实际导入显示；未改固件、业务字节协议或运行中的接入 token。
