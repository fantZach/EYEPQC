# 三端 MVP 软件推进记录

更新：2026-10-13。三个 agent 分工板端、Windows PC、Android，主协调者审阅接口并执行跨端验证。
用户已报告校园网 PC 和手机临时 HTTP 页面互访成功；该事实只证明基本 TCP 连通，不是视频吞吐验收。

## 实现与证据

| 子项目 | 本轮交付 | 已验证范围 |
|---|---|---|
| 开发板 | `prepare_mobile.py`，新布局 G6 ARM ELF | BSP 125 源码构建、开发态 secure-cleanup profile；73 项来源/产物预检；公开身份导出/拒绝生产profile/私钥缓冲覆写等 6 项 mock 通过 |
| Windows PC | `relay.py`，固定 websockets 15.0.1 / pyserial 3.5 | 实际回环 WebSocket、模拟串口，9/9 测试通过（主协调者复验 7.102 秒），覆盖令牌/路径、拆粘包、独占、超限、半包、部分写失败和释放重连 |
| Android | 原生 Java Activity、OkHttp 4.12.0、BC 1.81 ML-KEM | 内核 147 项断言通过，其中包含 25 个公开 ML-KEM KAT、20 个 GCM KAT；另外 Activity 用 API 26 符号进行独立 javac 检查 |
| 三端交叉 | `sim/tb/test_three_end.py` | Android 实际 Java/OkHttp→实际 WebSocket 桥→模拟串口→板端 C session/ML-KEM→软件 GCM JPEG，两个独立连接、REKEY 和 STOP 均成功；1 个集成用例含 4 个会话，5.666 秒 |

板端软件输出：`build/vitis/g6_mobile_bridge_20261012_1`。
G6 ELF SHA-256：`0ce4be865df2b7d6aaecad4014957fdc5af4ee5123f8171dc720e65d0979388a`。
manifest SHA-256：`c4cd30d43499b2113eca0602d0ec1024ce299b901e0db50119841e249b4bfb02`。
复用 `build/vivado/g4_usb_1/m01.xsa`，XSA SHA-256 为 `1a0550ce10ad1c4f792d864f0aa4527a8491ce6260527ef4123dcd7d0140bc62`；
其 bit 与本机历史 G6 使用的 bit 相同。本轮重新编译 ARM 软件，没有重新实现 PL 或下载到板卡。

主协调者用准备入口实际执行了默认公开导出（无 JTAG）：`board/output/mobile_identity_20261013`，
含 800 字节 `public.bin`、`public.sha256` 和公开 JSON；73 项预检通过，`jtag_provisioned=false`、
`authenticated_video_verified=false`，没有读取/导出私钥。手机导入时需独立核对指纹。

四次跨端认证 JPEG 的参考 SHA-256 均为 `053ba3cfaa918598832bfa25b7ad02be78835551bcbe1b4be502cd530e328275`。
原始图像是软件生成的公开 640×480 RGB JPEG fixture，不是相机实拍；不输出业务密钥或图像载荷日志。

集成过程中修正了 REKEY 后旧视频已排队、到新 ACK 前错误进入新握手状态的问题。
显式换钥期间只排空旧 session 的完整视频记录，新 ACK 后关闭窗口，普通握手前视频仍拒绝。
新增旧帧/新 ACK/Finished/新视频和跨真实 WebSocket 的换钥回归；不将旧包视为认证或显示通过。
STOP 使用发送后优雅 WebSocket 关闭，集成测试确认板端 C 实际收到认证 STOP，避免立即取消连接丢失已排队命令。

Android 正式 Gradle 构建通过：31 tasks、2 分 28 秒。初次官方下载 TLS 失败后，从官方备用域名/Google CDN
通过本机已有代理取得并校验 SDK，临时 Gradle init 与工具缓存位于忽略目录，没有改变系统代理或项目默认仓库。
调试 APK 为 `mobile/app/build/outputs/apk/debug/app-debug.apk`，4,633,066 字节；SHA-256 为
`84190c59ce9f78bc8f690eefdb04515510c594218bf35a9a3638818953e08431`。
APK v2 签名验证通过（Android Debug RSA 2048），aapt 确认包名 `org.eyepqc.mobile`、版本 0.1、最低 API26/目标35、
启动 Activity 与 INTERNET 权限。本轮未安装到手机，不能将产物构建成功记为真机验收。
板端准备/PC/审阅包联合 pytest 24 passed、54 subtests passed（6.92 秒），文档与脚本检查通过。

## 边界与下一步

- 本机最新只读串口枚举仅 COM4 CH340，没有 VID03FD/PID7020 视频 CDC；未连接/操作视频口、JTAG、启动介质或手机。
- Android APK 已完整构建并验签，实际手机运行待验；纯 JVM 互操作不代表 Android 系统与真实板端运行。
- 新的业务流仍需真实板卡与 Android 手机联调、十分钟稳定性、STOP/REKEY/重连及 45 fps 显示测试；G8/G9 未通过。
- 旧 G0/G7 与生产安全待办不改变。开发私钥/seed 仍由可信 PC/JTAG 提供，纯转发实现不能消除该 provisioning 信任边界。
- 公网中转和组网 VPN 尚未部署。局域网明文 WS 会暴露接入令牌，仅限可信网络；公网使用 WSS。

运行步骤见 [三端 MVP 指南](../doc/three_end_mvp.md)。源码与公开向量可提交，固件/JAR/SDK/APK/测试私钥留在忽略目录。
