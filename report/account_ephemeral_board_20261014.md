# 2026-10-14：账号与临时 ML-KEM 实机验证

本轮实际链路为 CF7020B/OV5640 → USB CDC COM7 → Windows WSS → 客户端。
固件使用 `build/vitis/g6_account_ephemeral_20261014_2`，75 项构建哈希/ARM 启动预检通过后，
通过 JTAG 临时下载并注入开发身份私钥和测试种子；没有更新 SD、Flash 或 eFuse。
公开身份导出到 `board/output/mobile_identity_account_live_20261014_1`。
SD 仍为此前 G0 自检镜像，断电后不会自主启动本次视频固件。

## 可复核的 PC/JVM 测量

真实账号 WSS 服务使用专用测试 CA、有效地址校验和身份 pin；没有关闭 TLS 校验。
`LiveProbe --account` 从本机私有凭据文件读取账号密码，不将密码放入命令行或测试输出。
这只是 JVM OkHttp/ImageIO 测量，不是 Android UI 帧率。

| 采集目录（data/captures 下） | 认证并解码帧 | 首末帧跨度 | 帧率 | 尺寸 |
| --- | ---: | ---: | ---: | --- |
| account_live_20261014_1 | 1421 | 30.0465811 秒 | 47.25995265 fps | 640×480 |
| account_live_20261014_2 | 475 | 10.0288435 秒 | 47.26367502 fps | 640×480 |

两轮 `result.json` 均 PASS，首末 JPEG 已保存，每帧完成认证与 ImageIO 解码。
最大帧间隔分别为 0.0884428 / 0.0549292 秒。
两轮正常 STOP 后重新建会话，无重新下载固件：relay 分别记录正常关闭 code=1000、
stop_forwarded=1、error=none，转发 12800 / 4285 条记录，queue_peak=4。
原始服务日志保留在 ignored `tmp/preboard_20261014_r1/relay_board_live.log`。

## Android 真机反馈

用户在 0.6 APP 导入本轮 schema2 pairing.json，使用 viewer 登录后回复“帧率45，成功”。
随后按 STOP/重新连接/手动换钥的测试提示回复“换药后45帧”，本报告按上下文理解为“换钥后45帧”。
据此记录手机显示视频及手动换钥后约 45 fps 的用户观察，不冒充仪器计时或抓取的 UI 数据。
relay 同时记录手机端 `10.194.103.178` 的第一次会话正常 STOP：code=1000、
stop_forwarded=1、32198 条转发记录、79.844 秒、error=none；随后同一手机新连接已建立。
手机端换钥成功的依据是用户反馈，不仅凭 relay 控制消息数量推定。

## 验证范围和后续

- 本轮完成真实板卡 suite2 账号视频短测、PC STOP/重连，以及手机视频/手动换钥反馈。
- 尚未覆盖实际 1785/1800 秒自动换钥、双设备账号接管、完整 G8 长测与故障门禁。
- 没有读取本轮板端 fatal/control/transport 计数，不能声称这些计数为零。
- 开发态私钥/种子经可信 PC/JTAG 注入，不能声称生产安全、可信板端熵源或对 PC 的前向保密。
- 本次复用已有测试客户端，仅增加账号模式和凭据解析自检；没有新增运行时依赖或修改 APK。
