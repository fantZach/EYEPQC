# 三端实机准备与 JVM 摄像头接收（2026-10-13）

用户已报告手机安装初版 APK；本轮由代理负责板端装载、Windows 接入及可自动化的接收验证。
没有通过 ADB 操作或安装手机，也没有测量 Android Activity 显示帧率。

## 板端与接入准备

- JTAG 识别 XC7Z020/APU/Cortex-A9，临时加载 `build/vitis/g6_mobile_bridge_20261012_1`；73 项预检通过。
- 使用开发态 JTAG 注入测试私钥/新 seed，未写 SD、Flash 或 eFuse。摄像头、PL GCM、DMA 和实际 USB CDC 均参与接收测试。
- 视频 CDC 为 COM7（VID03FD/PID7020）；COM4/CH340 仅调试串口。
- 接入地址为 `ws://10.179.236.247:8765/stream`，绑定当前校园网接口；明文 WS 仅供可信开发局域网使用。
- 本地配对资料为 `tmp/mobile_pairing/pairing.txt` 与 `relay.token`；访问令牌不进入本报告或 Git。
- `http://10.179.236.247:8766/` 仅服务 `tmp/mobile_pairing/public/`，包含 800 字节公钥、公开 pin 和调试 APK，绝不服务配对父目录/私钥目录。
- 公钥下载逐字节长度与 SHA-256 已检查；手机 pin 仍须从可信本地配对文件独立确认，不只信任 HTTP 下载的摘要。

## 实际接收窗口与失败记录

测试接收端是 PC 上的实际 Java/OkHttp、同源 Session 和 ImageIO。首次完整认证 JPEG 后起计时；
软件不生成视频，输入来自真实 OV5640→PL/DMA/AES-GCM→USB→PC 密文桥。
图像只保存首/末帧到 Git 忽略目录，不经公开 HTTP 服务明文图像。

| 捕获目录（`data/captures/`） | 接收窗口 | 结论 |
|---|---|---|
| `mobile_java_live_20261013_1` | 1421 帧 / 30.036908 s / 47.275172 fps / 640×480 | 视频接收 PASS；原关闭逻辑的后续恢复失败，不能宣称完整恢复通过 |
| `mobile_java_live_20261013_2` | 0 帧 | FAIL；停止后重连失败。AP0 元数据 ready=0/status=2/fatal=1/transport=1/control=0，固件已进入终态保护 |
| `mobile_java_live_20261013_3` | 1420 帧 / 30.0159793 s / 47.274819 fps，最大间隔 0.052533 s | 加入 STOP 残余排空后视频 PASS，STOP drain quiet；当次停止后读回 fatal/control/transport 均为 0 |
| `mobile_java_live_20261013_4` | 0 帧 | FAIL；HELLO 已转发但无 USB 记录返回，板端诊断仍 healthy。不把 ACK 超时写成认证成功 |
| `mobile_java_live_20261013_5` | 1420 帧 / 30.0264062 s / 47.258403 fps，最大间隔 0.0508111 s | 视频 PASS，但 STOP drain invalid/code1008，关闭子项失败；单独保留，不合并为成功恢复 |
| `mobile_java_live_20261013_6` | 1421 帧 / 30.0463574 s / 47.260305 fps，最大间隔 0.088765601 s | 用户断电重启后，最终候选首个会话视频 PASS、STOP drain quiet/code1000 |
| `mobile_java_live_20261013_7` | 1419 帧 / 30.004486201 s / 47.259599 fps，最大间隔 0.042742401 s | 不重新下载/注入、不拔线的第二会话，视频 PASS、STOP drain quiet/code1000 |

其后恢复作业时读回出现 AP transaction timeout；重连本机 hw_server 后仍只有 DAP（status `0x30000021`）与 FPGA，
没有 APU。无法仅根据时间先后归因为 STOP。用户断电重启后 APU/两核恢复，代理再次临时装载相同固件。
新 seed 与会话独立生成，公钥/pin 和配对 token 保持不变。
最终两个连续会话结束后只读 AP0 元数据显示 ready=`910644037`、status=1、fatal/control/transport=0，
phase 字节 0（WAIT_HELLO）、tx_ready=1。该读回只读公开元数据，不读密钥或图像载荷，也不证明全域清零。
两个 STOP 排空分别丢弃 6 条残余记录/7559 字节与 6 条/7275 字节，均达到 quiet。

## 修正及验证边界

- 正常 STOP 后关闭网络连接，PC 保留 DTR，读完合法残余 USB 记录到 150 ms quiet，最长 2 秒；非法记录仍关闭，不扫描或拼接重同步。
- Windows 串口改为 20 ms 正超时、一个后台读取，避免只查询空 cbInQue 而不提交实际 ReadFile 的风险。
  取消时先等待自然读取完成（最多 250 ms），完整保留已读尾字节；超限才 CancelIoEx，读取退出前不关闭/排空端口。
  这是依据对照试验采取的修正，不能仅凭软件测试宣布 Windows/板端交付根因已完全查明。
- 同板原 Python `g6_board --no-jtag --seconds 3 --debug-stage --drain-stop` 对照成功，HELLO_ACK 无重试立即收到，约 47.39 fps，
  原始记录为 `data/captures/g6_usb_20261013_015635_680699/`。
- Android 0.2 加入相同 HELLO 最多两次有界重试，每次间隔 3 秒；15 秒总握手期限不延长。
  WAIT_FINISHED 仅忽略与已校验 ACK 字节完全相同的重复记录，不接受变化 ACK 或流式阶段 ACK。
- APK 0.2/versionCode2 已构建、验签，沿用旧调试证书，可覆盖初版。文件 4,633,646 字节，SHA-256
  `0aa8afe434e9631661330e8d2739f3b82e152473b0c9acc8eaba0d9191a9c06d`，公开下载副本已校验一致。
- Android 核心 158 项断言通过；板端/PC/审阅包联合 36 passed、61 subtests passed（11.95 秒）；五会话跨端软件互操作含丢首 ACK 重试通过。
- `LiveProbe --self-test` 检查 JPEG 解码/尺寸、首末图片、短窗口拒绝、过长间隔拒绝等通过。

手机仍需覆盖安装 0.2、导入公钥和可信 pin/token、实际连接并反馈显示帧率；G8/G9 与完整 G7 尚未通过。
JVM 的约 47.26 fps 不代表手机显示帧率，短窗口也不代表十分钟稳定性或生产级安全。
交接时接入/公开下载服务仍在运行：8765 与 8766，板端等待新 HELLO。地址和进程状态以本轮运行时为准。
手机先从公开服务更新 APK/下载公钥，令牌及 pin 从本地私有 `pairing.txt` 获取；保持应用前台亮屏，结束优先 STOP。
