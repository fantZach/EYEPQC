# Windows / Android 无中继 P2P 首轮试验

2026-10-14 用户授权先测试直接 P2P，再决定是否租公网视频中转服务器。
不更改板卡、现有 WSS/suite2、账号或 SD；这一步只验证合成数据的连接/校验/吞吐。

## 开源方案与最小实现

- PC：[aiortc](https://github.com/aiortc/aiortc)，BSD-3-Clause；本轮固定 1.15.0，使用 asyncio/ICE/DTLS/SCTP DataChannel。
- Android 首轮复用系统 WebView 内置 WebRTC，在独立 `org.eyepqc.p2pprobe` APK 中加载固定本地页面；无第三方脚本、原生 JS bridge、摄像头权限或账号读取。无需为连通性测试引入完整音视频 SDK。
- 后续原生 Android 候选：[GetStream/webrtc-android](https://github.com/GetStream/webrtc-android)，Apache-2.0，提供 `org.webrtc` API；本轮未引入该依赖，也不依赖 Stream 的托管服务。
- 默认 STUN 使用 Cloudflare 公共 `stun:stun.cloudflare.com:3478`，依据[官方说明](https://developers.cloudflare.com/realtime/sfu/get-started/connection-patterns/)。STUN 用于候选发现，不转发测试负载；会接触客户端公网端点。
- 不配置 TURN、不设置视频轨道；一个有序可靠 DataChannel 传输 1459 字节合成包，负载及连续序号逐包核对，最后 ACK + DONE 确认全部接收。PC 发送缓冲上限 64 KiB。

## 操作

独立测试 APK：`mobile/p2pprobe/build/outputs/apk/debug/p2pprobe-debug.apk`。
安装后显示“EYEPQC P2P测试”，不会覆盖或改变现有 EYEPQC 0.6 APP。
Android System WebView 必须支持 WebRTC，支持性仍须真机确认；不支持时会明确提示。

PC 环境与运行（仓库根目录 PowerShell）：

```powershell
./.venv/Scripts/python.exe -m venv build/p2p_venv
./build/p2p_venv/Scripts/python.exe -m pip install --only-binary=:all: -r pc/requirements-p2p.txt
./build/p2p_venv/Scripts/python.exe pc/src/host/p2p_probe.py --output tmp/p2p_run_1 --seconds 30 --mbps 5
```

输出目录须不存在。启动进程保持运行，生成 offer 后最多等待十分钟：

1. 手机关闭 Wi-Fi，用移动网络打开测试 APP；PC 保持校园网连接。
2. 用自己的可信文件传输/聊天工具，把 offer.json **原文**复制到手机的 offer 输入框，点击“生成 answer”。不可修改 SDP、指纹、地址或删减 ICE 候选。
3. 将手机 answer 输入框完整内容保存到同一输出目录的 answer.json。保持手机测试页前台和 PC 进程运行。
4. 交换后等待最多45秒连接；发送30秒、目标5Mbps合成负载，最后最多15秒等待接收确认。
5. 以 PC result.json 确认完整接收与测得吞吐；手机还显示选中的 host/srflx/prflx 候选类型和协议。实际30秒测量与足够吞吐缺一不可，不以“已连接”单独通过视频可用性。

offer/answer 包含临时 ICE 凭据、DTLS 指纹和网络端点，只交给自己的设备，保存在 ignored tmp，不公开上传。
手动交换依靠可信传递，没有项目账号认证，因此本工具禁止接真实 USB、视频明文或业务密钥。
后续若集成业务，必须保留登录/身份认证、ML-KEM、AES-GCM、重放检查、STOP/换钥和有界流控；不允许把本探针当作认证替代。

## 证据边界

两端不配置 TURN，且拒绝 SDP 中 relay 候选，但这并不能排除系统 VPN/Mihomo/TUN 在底层转发 UDP。
若要证明物理校园网↔移动网直连，需单独确认两端代理/VPN路径；本轮不自动关闭代理或修改防火墙。
UU 的 P2P 成功不迁移成此工具的通过证据。STUN 候选缺失、打洞失败或缓冲停滞须保留失败，不增加隐藏中继。
没有异网直连实测前，暂不替换可工作的 WSS 视频通道。

定向检查：

```powershell
./build/p2p_venv/Scripts/python.exe -m unittest discover -s pc/p2p_tests -v
node mobile/test/p2p_probe_check.js
# 已安装 SDK35/JDK17+/Gradle8.9 的环境：
gradle --no-daemon -p mobile :p2pprobe:assembleDebug
```

Windows 本机 Proactor UDP close 曾挂起；独立入口使用 SelectorEventLoopPolicy，实测校验与关闭完成。
本机数据通道的性能测试关闭 asyncio 调试开销，初次 debug loop 约1.09Mbps失败保留为调查事实，不放宽实际手机吞吐目标。

最终复跑三项 PC 检查与 JS 检查通过；本机一秒第二窗口为422包/4.925584Mbps，仅作合成链路功能证据。
原 Android 核心160 / JSON39 / 临时KEM37检查仍通过。
探针 debug APK SHA256：`39fadd6d00f89a41a30590d60745201d1d4f4d9f6aee5b9f574c2c0e7befb68e`，v2 验签通过。
当前 PC 对 Cloudflare STUN 的真实收集返回两个 host、一个 srflx 候选并正常关闭；
这仅证明本次候选发现成功，不证明手机端打洞成功，也不排除当前 Mihomo/TUN 底层路径。
