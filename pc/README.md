# PC 子项目

负责开发板的 USB 接入、主机调试和网络密文转发。可选远程中转服务也由本子项目维护，
服务可部署在 PC 或远程主机；局域网 MVP 不需要购买服务器。

用户已确认 PC 使用 **Windows**，观看端使用 **Android**。PC 接入服务首先供同一局域网内的
Android 手机连接；也可由两端加入组网 VPN 后，手机使用 PC 的 VPN 地址连接同一服务。
VPN 产品尚未选定，校园网直连或中继的可达性、吞吐与延迟须实际测试。

## 已有代码

`src/host/` 从原仓库根目录 `src/host/` 完整迁入，包括：

- `g6_board.py`：开发态 JTAG provisioning、USB ML-KEM 握手、AES-GCM 视频接收。
- `handshake.py`、`protocol.py`：会话参考、字节协议及流解析。
- `demo_window.py`、`demo_controller.py`：PC 本地预览、换钥、录像与回放。
- `m09.py`：ML-KEM C 库适配及开发测试密钥工具；库源码共享 `../board/src/third_party/mlkem/`。
- `build_manifest.py` 与其他模块工具：构建预检和离线/板级验证。
- `relay.py`：Windows USB CDC 与二进制 WebSocket 双向纯密文桥，不导入握手、密钥派生或解密模块。

原有 G6/演示程序在 PC 持有密钥并解密，是测试接收端；新 `relay.py` 单独执行纯转发。
不要同时运行这两种接收路径，也不能调用 `HostSession` 替手机执行握手后仍宣称 PC 看不到视频。

## 运行

在 Windows 上使用 PowerShell，从仓库根目录安装 `requirements.txt`，使用 Python 3.12+
及根目录 `.venv`：

```powershell
& ./run_demo.ps1 -Mode Demo -Offline
& ./.venv/Scripts/python.exe pc/src/host/g6_board.py --help
& ./.venv/Scripts/python.exe sim/tb/test_g6.py
```

板端构建、烧录和验收工具位于 `../board/prj/`；仓库级入口继续为 `../run_demo.ps1`。
不要直接复用迁移前清单执行板测，先按 [根说明](../README.md#目录迁移与构建注意事项) 重建并预检。

现有 G6 工具按 `VID_03FD&PID_7020` 自动发现唯一的板卡视频 USB CDC 端口。
Windows 分配的 COM 编号可能改变，应区分视频 CDC 与板卡调试串口。
视频 CDC 只能由一个程序独占，启动转发器前须关闭占用它的演示或测试接收程序。

Android 使用 PC 的局域网地址或组网 VPN 地址接入；`localhost` 仅供 PC 本机。
须确认服务监听该网络接口，并在 Windows 防火墙中仅放行所需程序/端口与访问范围。
校园 Wi-Fi 的客户端隔离也可能阻止同网段连接，届时分别验证局域网和 VPN 路径。

## 单观看端密文转发

先关闭现有 G6/演示接收器。从根目录执行：

```powershell
& ./.venv/Scripts/python.exe -m pip install -r pc/requirements.txt
# 只在首次配对时生成；文件包含接入凭据，勿提交或公开。
& ./.venv/Scripts/python.exe -c "from pathlib import Path; import secrets; p=Path('tmp/relay.token'); p.parent.mkdir(exist_ok=True); p.write_text(secrets.token_urlsafe(32), encoding='ascii')"
# 默认仅监听127.0.0.1；将地址替换为本机实际局域网或VPN地址。
& ./.venv/Scripts/python.exe pc/src/host/relay.py --token-file tmp/relay.token --host 192.168.1.10
# 仅软件回环检查，不打开实际USB。
& ./.venv/Scripts/python.exe -m unittest discover -s pc/tests -v
```

板卡须已运行对应固件并完成开发态 provisioning，转发器不烧录或注入板端密钥。
`--serial-port COM16` 可覆盖视频 CDC 自动发现，须使用实际枚举号。默认端口 `8765`，
Android 连接 `ws://<PC地址>:8765/stream`，HTTP 握手携带 `Authorization: Bearer <文件中的token>`。
手机通过可信途径导入该接入 token 和独立的板卡公钥；token 不是视频密钥。
纯 WS 会明文传输接入 token，仅在可信局域网或已建立的受保护组网 VPN 中使用。
WSS 可通过 `--tls-cert <证书.pem> --tls-key <私钥.pem>` 启用，Android 须信任有效证书。

已有板端身份文件时，可用最小配对工具同时准备手机公钥与本地接入凭据。它核对 800 字节公钥和
SHA-256 pin，只读取 `public.bin` 与 `public.sha256`，输出目录必须不存在：

```powershell
& ./.venv/Scripts/python.exe pc/src/host/prepare_pairing.py --identity-dir board/output/mobile_identity_live_20261013_1 --endpoint ws://10.179.236.247:8765/stream --output-dir tmp/mobile_pairing
& ./.venv/Scripts/python.exe pc/src/host/relay.py --token-file tmp/mobile_pairing/relay.token --host 10.179.236.247
```

将示例身份目录和 PC 地址换成当前实际值。`tmp/mobile_pairing/pairing.txt` 包含 endpoint/token/pin，
供本机查看和手机配对；`relay.token` 供桥读取。两者都属于接入凭据，不能通过公钥下载服务公开。
只有 `tmp/mobile_pairing/public/` 包含可公开的公钥和摘要；如临时开启 HTTP 下载，文档根目录必须精确
指向这个 `public/` 子目录，绝不能服务配对父目录或板端身份目录。pin 仍须经可信途径确认，不能只信任
同一未认证 HTTP 下载的摘要。工具 stdout 只显示文件路径，不打印 token。
POSIX 上凭据以 0600 创建；Windows 继承父目录 ACL，保存到当前用户可控目录并限制其他用户访问。

每个二进制消息只承载一条完整 USB 外层记录；手机只可发送合法的 HELLO、KEM_CIPHERTEXT、
FINISHED_HOST、START、STOP、REKEY 控制。板端控制与视频原字节转发，PC 不参与业务密钥派生或解密。
路径错误返回 HTTP 404，token 缺失/错误返回 401，已占用返回 503；同时升级竞争时第二连接关闭 1013。
文本、越界、非法控制方向或半包超时关闭连接，单条 WS 消息上限 1459 字节。

应用发送队列最多 64 条记录（单条最多 1459 字节），USB 未完成记录超时 2 秒，
网络发送超时 5 秒，串口写超时 250 毫秒。超限关闭整个会话，不抽取控制消息丢弃后继续播放。
Windows 串口使用 20 ms 正超时、单个后台读取；取消先等待读取自然返回（最多 250 ms），超限才取消 I/O，
读取结束后才排空/关闭端口。正常 STOP 后保留 DTR，合法残余记录排空到 150 ms quiet（最长 2 秒）。
每次接入先拉低 DTR 250 毫秒、清除旧缓冲，再拉高开始转发；断连拉低 DTR、清空缓冲并释放串口。
Android 重连须重新完成握手；实际板端 DTR/故障恢复仍待 G7 验证。

桥已通过真实 WebSocket 与模拟串口离线测试，并在真实 G6/摄像头/USB→JVM 两个连续 30 秒窗口达到约 47.26 fps、
正常 STOP/重连通过。Android 真机显示、45 fps 与校园网/VPN 手机吞吐尚待联合验收；
之前的失败和严格边界见 [实机记录](../report/mobile_live_bringup_20261013.md)。可选公网中转配对、部署及 PC 主动连接中转仍未实现。
实现使用 [websockets 15.0.1 asyncio 服务端 API](https://websockets.readthedocs.io/en/15.0.1/reference/asyncio/server.html)。
详细约束见 [三端架构](../doc/architecture.md)。
