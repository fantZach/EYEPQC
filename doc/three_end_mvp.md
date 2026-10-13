# 局域网三端 MVP：准备与联调

Windows PC ↔ Android 的校园网基本 TCP 连通由用户报告验证成功。
本轮已实现软件链路，实际板卡/Android 视频、帧率、断连恢复须按 G8 单独测量。
已临时装载 G6 并完成真实板卡→PC 密文桥→Java 客户端的短窗口认证解码，约 47.26 fps；不是手机显示结果。
手机安装初版后，请用 [mobile README](../mobile/README.md) 中的 0.2 修正版覆盖更新，包含 HELLO 容错。
共享协议保持不变，纯密文桥与原 G6 解密演示必须独占运行，不能同时打开视频 CDC。

## 已有实现

- 开发板：新目录 G6 软件构建；`board/prj/prepare_mobile.py` 负责预检、公开身份导出及显式 JTAG provisioning。
- PC：`pc/src/host/relay.py`，`/stream`、Bearer 接入令牌、完整记录转发及有界队列，无业务密钥派生或解密。
- Android：原生 Java Activity、OkHttp 4.12.0、Bouncy Castle 1.81，公钥 pin、ML-KEM/Finished、GCM、反重放、JPEG 组帧与显示。

Android 最低 API 26，目标/编译 API 35。源码、离线内核、Java 网络互操作与调试 APK 均已有；APK 为 `mobile/app/build/outputs/apk/debug/app-debug.apk`，验签及版本记录见 [mobile README](../mobile/README.md)。
手机前台单观看端，离开界面关闭会话；旧视频只在显式 REKEY 到新 ACK 之间排空，不能交给新密钥解密。

## 运行顺序

1. 从根目录安装 PC 额外依赖：

   ```powershell
   & ./.venv/Scripts/python.exe -m pip install -r requirements.txt -r pc/requirements.txt
   ```

2. 核对板卡、摄像头、JTAG 和视频 USB Slave。COM4/CH340 是调试串口，不是视频 CDC。
   使用对应 G6 构建并导出公开身份；以下 `--provision` 会操作板卡，导出目录须全新：

   ```powershell
   & ./.venv/Scripts/python.exe board/prj/prepare_mobile.py --workspace build/vitis/g6_mobile_bridge_20261012_1 --identity-output board/output/mobile_identity_live --provision
   ```

   开发测试素材需先按原 M09/Prepare 流程生成。该入口不发起 PC 握手，板卡等待手机 HELLO。
   只将导出目录的 `public.bin` 交给手机，通过可信渠道独立核对 `public.sha256`，不要复制私钥目录。

3. 本地创建接入令牌并启动桥。生成示例拒绝覆盖已有令牌；`tmp/` 被 Git 忽略：

   ```powershell
   & ./.venv/Scripts/python.exe -c "from pathlib import Path; import secrets; p=Path('tmp/relay.token'); p.parent.mkdir(exist_ok=True); p.open('x', encoding='ascii').write(secrets.token_urlsafe(32))"
   # 把地址替换为 PC 当前校园网 IPv4；不要使用代理/TUN 的虚拟地址。
   & ./.venv/Scripts/python.exe pc/src/host/relay.py --token-file tmp/relay.token --host 10.179.236.247
   ```

   该 IPv4 只是本轮读取值，运行前用 `ipconfig` 重新确认。视频 CDC 自动发现唯一 VID03FD/PID7020，
   可用 `--serial-port` 指定实际视频口。只放行 Windows 防火墙中所需服务及访问范围。

4. 构建/安装 Android 调试 APK后，在应用输入 `ws://<PC地址>:8765/stream`、接入令牌，选择 800 字节公钥文件并输入可信指纹。
   点击连接，只有完成板卡 Finished 与认证 START 才显示完整 JPEG。
   明文 WS 会传输接入令牌，仅用于受信任的局域网或受保护 VPN；公网需 WSS 和有效证书。

5. 验证显示、STOP、关闭重连及 REKEY，记录实际手机认证/显示帧率、丢帧、网络吞吐和延迟。
   未同步时钟时，不把板端 timestamp 当作端到端延迟。45 fps 是待实测目标。

6. 再做 G8 十分钟与故障验证；公网服务仍待实现，G0/G7 与生产安全状态单独保留。

## 本机已准备的配对资料

`prepare_pairing.py` 可从公开身份生成独立 token、私有 `pairing.txt` 和只含公开材料的 `public/` 子目录。
本轮生成位置为 `tmp/mobile_pairing/`（Git 忽略），参数写在本地 `pairing.txt`，不从未认证 HTTP 服务暴露 token。
手机浏览器可从 `http://10.179.236.247:8766/public.bin` 下载公钥，从
`http://10.179.236.247:8766/EYEPQC-0.2.apk` 下载修正版。网络地址与服务存活状态仅对本轮有效。
APK/pin/token 的校验与测试流程见 [实机准备记录](../report/mobile_live_bringup_20261013.md)。
使用时保持手机应用前台亮屏，结束优先点“停止”，再关闭；网络异常、退出/拔插等完整 G7 场景仍待验收。

## 无硬件交叉验证

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s board/tests -v
& ./.venv/Scripts/python.exe -m unittest discover -s pc/tests -v
& ./mobile/test.ps1 -Jdk 'C:/path/to/jdk' -FetchDependencies
# 该测试使用 mobile/test.ps1 编译的 Java 类与固定依赖缓存；必要时设置 JAVA_HOME。
& ./.venv/Scripts/python.exe sim/tb/test_three_end.py
```

跨端测试让实际 Java/OkHttp 客户端连接真实回环 WebSocket 桥，模拟串口后方运行板端 C 会话和 ML-KEM，
软件 GCM 生成公开合成 JPEG。两个独立连接、认证换钥和停止共四个会话的 JPEG 哈希与参考一致，C 会话实际接收 STOP。
它验证三个语言/组件的互操作，不模拟 USB 控制器、PL GCM、相机或 Android 系统运行。
新的深度测试不加入每次提交的快速 hook。
