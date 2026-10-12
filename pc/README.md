# PC 子项目

负责开发板的 USB 接入、主机调试和未来的网络密文转发。可选远程中转服务也由本子项目维护，
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

这些程序当前会在 PC 持有密钥并解密，是测试接收端。未来的纯转发模式须单独实现，
不能调用现有 `HostSession` 替手机执行握手后仍宣称 PC 看不到视频。

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

网络服务实现后，Android 使用 PC 的局域网地址或组网 VPN 地址接入；`localhost` 仅供 PC 本机。
须确认服务监听该网络接口，并在 Windows 防火墙中仅放行所需程序/端口与访问范围。
校园 Wi-Fi 的客户端隔离也可能阻止同网段连接，届时分别验证局域网和 VPN 路径。

## 下一步：单观看端密文转发

1. 独占一个 USB CDC 端口，按原协议检查通道和长度，保留记录字节。
2. 向移动端转发视频/板端控制，向板卡转发移动端控制；PC 不参与 ML-KEM 密钥派生或视频解密。
3. 首先提供 Android 的局域网接入，再验证可选组网 VPN；如仍需要公网中转，PC 主动连接中转服务。
4. 实现连接授权、单观看端占用、队列上限、超时与断线重建；日志只记录非秘密统计。

网络适配、监听服务和公网部署目前均未实现。二进制 WebSocket 是拟定的最小传输方案，
公网须使用 WSS；实现与依赖选型在后续步骤落实。详细约束见 [三端架构](../doc/architecture.md)。
