# PC 子项目

## Windows 命令行 EXE

`pc/src/host/eyepqc.py` 提供统一前台入口；打包后只需单个 `eyepqc.exe`、外置 JSON 配置及配置引用的
本机材料，无需在运行机器安装 Python。Windows OpenSSH Client 仍须安装并在 PATH 中。

```powershell
# 在仓库根目录构建；仅首次/更新打包依赖时加 -InstallDependencies。
& ./pc/build_exe.ps1 -InstallDependencies
& ./build/pc_cli/dist/eyepqc.exe --version
& ./build/pc_cli/dist/eyepqc.exe --help
# 复制 pc/eyepqc.example.json 到 EXE 同目录为 eyepqc.json，再按实际文件位置编辑。
& ./build/pc_cli/dist/eyepqc.exe check
& ./build/pc_cli/dist/eyepqc.exe status
# 确认旧服务已正常退出后，才执行 run；Ctrl+C 停止本次启动的 relay 和 SSH 子进程。
& ./build/pc_cli/dist/eyepqc.exe run
```

构建使用独立 `build/pc_cli/venv`、固定 PyInstaller 6.22.3、console/onefile 模式。
产物不打入配置、账户、证书、SSH key、板端身份或任何 `tmp/` 内容；不会安装后台服务、自动重连或操作 JTAG。
示例所有路径均相对 **配置文件所在目录**；也可使用明确的本机绝对路径。
`run --config <文件>`、`check --config <文件>` 可选择其他配置，配置文件不能含内联密码或 token。
`serial_port: null` 自动发现唯一板卡 CDC；绑定固定 `127.0.0.1:8765`，SSH 默认云端 TCP2222。
`tunnel: null` 仅启动本机 relay；非空 tunnel 使用严格 host key 验证与专用身份文件。

`check` 读取所选的本机账户、公钥配对与 TLS 材料，验证格式及证书/私钥匹配，不打开 USB 或建立网络连接。
SSH 身份/known_hosts 仅检查路径与大小，不证明云端主机身份已实测。
`status` 只读 Windows TCP 快照，显示默认本机8765和远端2222相关连接；配置改用其他 SSH 端口时，
该端口不会被此快照列出。TCP 建立不代表 SSH 属于本入口、板卡就绪、手机登录或视频认证通过。

切换到统一 EXE 前，须由操作者正常停止原有独立 relay **以及** SSH 隧道；只停 relay 保留旧 SSH 时，
新隧道可能因云端反向端口仍被占用而退出，统一入口会停止新 relay。入口不会接管、查杀现有进程或改变账户选择。
当前8765已监听时，`run` 在读取配置/私密材料与启动 SSH 前拒绝运行。SSH 退出显示其数值返回码，
配置/TLS失败显示静态检查方向，不原样打印可能包含秘密的底层异常。

```powershell
# 交互输入新密码；拒绝覆盖，不把密码放到命令行。
& ./build/pc_cli/dist/eyepqc.exe account --file <新的私有账户文件> --username viewer
```

账户创建不自动生效。操作者须决定使用哪份账户文件，更新配置的 `accounts_file`，再正常重启入口。
已有 `accounts-new.json` 也不会被自动选中。外置配置应留在用户可控目录，限制 Windows 私有材料目录 ACL。
首次手机视频验证仍需已有 G6 固件、板端身份、有效 WSS 证书及匹配的 Android 配对；EXE 的 help/check
和离线 fixture 测试不能代替实板/手机通过 EXE 的联合验收。

## 登录后自动分发配对配置

Android0.7在账号登录成功后自动获取公开schema2，无需用户传JSON。PC启动时显式指定唯一公开配置：

```powershell
& ./pc/run_relay.ps1 -Mode Run -BindAddress 127.0.0.1 -AccountsFile tmp/cloud_wss_20261015_1/private/accounts.json -PairingFile tmp/cloud_wss_20261015_1/public/pairing.json -TlsCert tmp/cloud_wss_20261015_1/public/server-chain.pem -TlsKey tmp/cloud_wss_20261015_1/private/server-key.pem
```

将示例替换为本机材料；先检查现有监听和观看者，不重复启动。
Python直接入口参数为 `--pairing-file`。仅账号+TLS模式支持；省略时保留旧手动导入方式，下载路径返回404。
同一TLS端口只新增 `GET /pairing.json`，使用既有Basic/scrypt/限速与单哈希验证；未授权401、忙/限速429。
只加载这一份最大8KiB、严格四字段的schema2到内存，不开放目录，不读取身份私钥；内容不含密码/token。
响应application/json、no-store、nosniff。配置在启动时冻结，更新须检查无观看者后按正常流程重启relay。
下载不打开USB、不改变owner或触发接管，即使USB不可用也能交付公开配置；视频仍按原规则单观看端授权。
Android要求JSON endpoint与输入WSS地址完全一致；证书SAN须匹配该地址，云端通过原SSH隧道透明传输HTTPS。
首次公钥信任来自正确TLS服务，已有同地址指纹不静默改变，不能声称首次分发不信任PC或其TLS身份。
本功能不增加云账号服务、不上传账号/私钥到云端，也不解决已有发送积压/板卡故障。

可选直接 P2P 的独立连通性探针见 [P2P 首轮试验](../doc/p2p_probe.md)：
aiortc 固定版本安装在独立 build/p2p_venv，只发送合成数据，不打开 USB 或更改现有 WSS。

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
& ./.venv/Scripts/python.exe -c "from pathlib import Path; import secrets; p=Path('tmp/relay.token'); p.parent.mkdir(exist_ok=True); p.open('x', encoding='ascii').write(secrets.token_urlsafe(32))"
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

将示例身份目录和 PC 地址换成当前实际值。`tmp/mobile_pairing/pairing.json` 集成地址、token、公钥 hex 与 pin，
Android 0.3 选择这一个文件后自动读取所有参数。`pairing.txt` 保留供本机查看，`relay.token` 供桥读取；
这些都属于接入凭据，不能通过公钥下载服务公开，也不提交 Git。
已有服务运行时，可导出 JSON 并沿用原 token，无需重启服务或重新配对：

```powershell
& ./.venv/Scripts/python.exe pc/src/host/prepare_pairing.py --identity-dir board/output/mobile_identity_live_20261013_3 --endpoint ws://10.179.236.247:8765/stream --token-file tmp/mobile_pairing/relay.token --config-file tmp/mobile_pairing/pairing-sd.json
```

导出文件必须不存在，避免覆盖已有凭据；通过可信文件传输交给自己的手机。
只有 `tmp/mobile_pairing/public/` 包含可公开的公钥和摘要；如临时开启 HTTP 下载，文档根目录必须精确
指向这个 `public/` 子目录，绝不能服务配对父目录或板端身份目录。pin 仍须经可信途径确认，不能只信任
同一未认证 HTTP 下载的摘要。工具 stdout 只显示文件路径，不打印 token。
POSIX 上凭据以 0600 创建；Windows 继承父目录 ACL，保存到当前用户可控目录并限制其他用户访问。

每个二进制消息只承载一条完整 USB 外层记录；手机只可发送合法的 HELLO、KEM_CIPHERTEXT、
FINISHED_HOST、START、STOP、REKEY 控制。板端控制与视频原字节转发，PC 不参与业务密钥派生或解密。
路径错误返回 HTTP 404，token 缺失/错误返回 401，已占用返回 503；同时升级竞争时第二连接关闭 1013。
文本、越界、非法控制方向或半包超时关闭连接，单条 WS 消息上限 1459 字节。

应用发送队列最多 64 条记录（单条最多 1459 字节），USB 未完成记录超时 2 秒，
网络发送超时 5 秒，串口写超时 250 毫秒。视频帧首按packet_count预留整帧空间，空间不足则整帧舍弃，
继续读USB而非等公网发送；控制消息保留且溢出仍关闭，非法头/记录仍拒绝。新增video_frames_dropped/video_records_dropped统计。
每发送至少64KiB应用记录，通过标准WS Ping/Pong限制链路在途字节；Ping发送/等Pong合用5秒截止，
避免SSH/TCP大缓冲积压使移动端保活排在旧视频后。没有修改板端协议或放宽TLS/认证，也不改写转发密文。
单帧超过整个64记录预算时也舍弃；更高分辨率前需另行设计帧/字节预算。低带宽下以降帧保持会话，不保证原帧率。
Windows 串口使用 20 ms 正超时、单个后台读取；取消先等待读取自然返回（最多 250 ms），超限才取消 I/O，
读取结束后才排空/关闭端口。正常 STOP 后保留 DTR，合法残余记录排空到 150 ms quiet（最长 2 秒）。
每次接入先拉低 DTR 250 毫秒、清除旧缓冲，再拉高开始转发；断连拉低 DTR、清空缓冲并释放串口。
Android 重连须重新完成握手；实际板端 DTR/故障恢复仍待 G7 验证。

桥已通过真实 WebSocket 与模拟串口离线测试，并在真实 G6/摄像头/USB→JVM 两个连续 30 秒窗口达到约 47.26 fps、
正常 STOP/重连通过。2026-10-13 用户确认 Android 真机可显示视频、约 40 fps 已足够，不再优先优化 45 fps。
这是用户确认的功能/性能结果；G8 的 10 分钟记录、断网/慢消费者恢复及 VPN 路径仍须独立验证。
之前的失败和严格边界见 [实机记录](../report/mobile_live_bringup_20261013.md)。可选公网中转配对、部署及 PC 主动连接中转仍未实现。
实现使用 [websockets 15.0.1 asyncio 服务端 API](https://websockets.readthedocs.io/en/15.0.1/reference/asyncio/server.html)。
详细约束见 [三端架构](../doc/architecture.md)。

## 服务状态、停止与 SD 板测配合

从根目录执行只读状态查询；它列出 8765/8766 的监听、TCP 对端与 PID，不读取 token 或打开 USB：

```powershell
& ./pc/run_relay.ps1 -Mode Status
```

`Established` 只证明 TCP 建立。8765 对端结合 `RELAY_SESSION_OPEN` 才表示接入授权已通过并打开 CDC；
桥无法证明手机 Finished/验 Tag/显示成功，须同时看手机状态。8766 下载连接不属于观看连接。
单纯 `RELAY_READY` 也不证明固件或公钥匹配：桥在观看者接入时才打开视频 CDC。

使用现有 token 前台运行，新入口遇到端口已有监听直接拒绝，不重复启动或结束其他进程：

```powershell
& ./pc/run_relay.ps1 -Mode Run -BindAddress 10.179.236.247
# 如 Windows PowerShell 的执行策略阻止脚本，仅对本次进程指定：
powershell -NoProfile -ExecutionPolicy Bypass -File ./pc/run_relay.ps1 -Mode Run -BindAddress 10.179.236.247
```

正常停止：先在手机点停止，等待 `RELAY_STOP_DRAIN outcome=quiet` 与 `RELAY_SESSION_CLOSE`，再在服务终端按
Ctrl+C。没有观看者时可直接 Ctrl+C；服务退出时释放 CDC。`outcome=timeout` 表示已触达 2 秒排空上限，
不能算板端 STOP 成功。掉线/强制退出靠 DTR 清理，不能代替实板故障恢复验证。

原后台服务如没有可操作终端，仅在协调者明确要求暂停、手机已停止且 8765 无 `Established` 后，
按 [PC SD 配合记录](../report/pc_sd_service_20261013.md) 重验命令行身份，再结束确认的 relay PID。
8766 只服务公开下载，不占 CDC，可保持运行。不要使用按进程名称批量结束、盲杀 Python 或自动重置板卡。
Board 完成 SD 启动并交还视频 CDC 后，再以前台入口恢复；默认自动发现唯一 `VID_03FD&PID_7020`，
只有实际枚举需要时才加 `-SerialPort COM7`。此入口不操作 COM4、JTAG 或 SD。

日志可在服务终端追加保存到 ignored `tmp/`：

```powershell
& ./pc/run_relay.ps1 -Mode Run -BindAddress 10.179.236.247 2>&1 | Tee-Object -FilePath tmp/pc-relay-sd.log -Append
```

新版 `RELAY_SESSION_CLOSE` 包含异常类型/固定原因、发送记录数/字节数、队列峰值和连接时长，
不包含 token、控制正文、业务密钥或 JPEG。发送记录包含控制与密文分片，不能换算为手机 FPS。
旧服务不会自动加载源码改动；明确停服后恢复才使用新日志。
若 SD 固件身份发生变化，使用 Board 交付的公开 `public.bin`/pin 导出新的私有 JSON，复用现有 `relay.token`；
不要读取或复制板端私钥，不把 JSON 放到下载目录。若仅 PC 地址变化，同样重新导出 endpoint 并在手机导入。

常见排查：401 检查手机配置与 token 是否对应；503 检查旧观看连接/清理窗口；1011 检查 USB 枚举、
端口独占、写入/发送超时与板端启动；1008 检查记录长度/方向、半包超时或队列溢出。
2026-10-15已修复普通G6固件发送期间DTR/epoch断连分类和开发态FAULT错误复活；
实板强制关闭客户端后无需重刷即可重连，以及0.524Mbit/s限速/整帧丢弃证据见 [握手修复](../report/handshake_recovery_20261015.md)。
先保存桥日志及手机错误，再由 Board 记录 `fatal/transport/control`，不要反复无依据 provision/复位。

## WSS 账号模式与 schema2

账号模式仅允许 TLS，通过 HTTP Basic UTF-8 每次认证，不能使用 Bearer 绕过。
以下仅为部署命令；执行前需要协调者交还设备，本次不启动服务。

```powershell
# 交互输入密码，创建新的私有账号文件；拒绝覆盖，密码不作为命令行参数。
& ./.venv/Scripts/python.exe pc/src/host/accounts.py --file tmp/accounts.json --username viewer
& ./pc/run_relay.ps1 -Mode Run -AccountsFile tmp/accounts.json -TlsCert tmp/server.pem -TlsKey tmp/server-key.pem -BindAddress <当前PC地址>
# 公钥来自可信Board交付目录；省略token-file导出schema2，目标必须不存在。
& ./.venv/Scripts/python.exe pc/src/host/prepare_pairing.py --identity-dir <公开身份目录> --endpoint wss://<证书SAN匹配的主机>:8765/stream --config-file tmp/pairing-account.json
```

schema2 仅含 version=2、endpoint(wss)、public_key_hex、public_key_sha256；不含密码/token。
原带 token 的 v1 导出、明确选择 `--token-file` 的开发模式继续兼容，账号文件与 token-file 互斥。
自签证书必须通过可信渠道把 CA 导入 Android，并让应用信任该 CA（Android 应用未必默认信任用户 CA）；
仍校验主机名/SAN，不能关闭证书验证。证书私钥和账号文件留在私有目录，Windows须限制父目录ACL。

账号文件为用户名到 `{salt: 16字节hex, hash: 32字节hex}` 的映射，固定 scrypt N=131072/r=8/p=1，
maxmem=256MiB。不提供低成本生产选项；旧试验低成本哈希不能沿用，应重新创建账号文件。
全局单进程限速为5次突发、每秒恢复1次，同时最多一个后台哈希；忙时429，未知账号也走dummy hash。
限速可能让其他用户暂时无法登录，现有视频转发继续运行；多进程部署前须替换该限速方案。

`/stream` 错误/缺失 Basic 返回401；同账号已有观看端返回409；不同账号占用返回503；限速429。
新设备得到409后必须由用户明确确认，才连接 `/stream?takeover=1` 并再次提供Basic。
PC认证正确后先撤销旧owner控制权限，以4409关闭旧端，等待旧USB清理完成才打开新串口。
旧设备收到4409应停止自动抢回。并发接管由同一锁串行处理，最多一个USB owner；清理失败/超时或
STOP持续排空超过2秒则封锁后续连接，须检查日志与设备后手动重启服务，不能自动强抢。

suite2 HELLO/ACK及type10(body864，板→手机)/type11(body832，手机→板)可原样转发。
PC仅验证长度/方向，不处理临时KEM、MAC或业务密钥；完整契约见 [suite2](../doc/account_ephemeral_protocol.md)。
账号TLS和软件回环通过不代表手机、实板、新SD固件或生产密码协议已通过。

## 公网反向 TCP 隧道（代码准备，未部署）

采用 Windows OpenSSH 把云端公开 `0.0.0.0:8765` 转到 PC 的 `127.0.0.1:8765`。
云端使用独立 sshd 的 TCP2222 和专用用户 `eyepqc-tunnel`，不修改已有管理 SSH22。
PC 沿用账号 WSS relay，账号校验、409 接管、USB 清理和队列仍在 PC；隧道和云端只转发字节，
不执行视频/KEM解密。SSH 上行公钥授权不替代手机用户名密码。

在仓库根目录使用现有 `.venv`；需安装 Windows OpenSSH Client 并将 `ssh.exe` 加入 PATH。
IdentityFile 必须为专用本机 SSH 私钥，known_hosts 必须通过可信渠道核对**独立 sshd** host key 后准备。
非标准端口的 known_hosts 项使用 `[云端地址]:2222`。工具只检查文件存在且非空，不读取私钥或证明 host key 可信；
不能直接信任未经核验的 ssh-keyscan 输出。下面都是需要用户提供的本机路径，不在聊天发送私钥。

```powershell
# 默认 Plan 只输出 argv 和检查路径，不启动 ssh、不读取文件正文、不联网。
& ./.venv/Scripts/python.exe pc/src/host/cloud_tunnel.py --cloud-host <云端IPv4或域名> --identity-file <专用SSH私钥路径> --known-hosts <已核验known_hosts路径>
# Check 仅调用 ssh -G 解析有效配置，不连接服务器，也不验证实际云端host key。
& ./.venv/Scripts/python.exe pc/src/host/cloud_tunnel.py --mode Check --cloud-host <云端地址> --identity-file <专用SSH私钥路径> --known-hosts <已核验known_hosts路径>
# 云端部署/网络/host key完成并明确授权后，显式Run才建立前台隧道。
& ./.venv/Scripts/python.exe pc/src/host/cloud_tunnel.py --mode Run --cloud-host <云端地址> --identity-file <专用SSH私钥路径> --known-hosts <已核验known_hosts路径>
```

默认 SSH2222，可用 `--ssh-port` 改为与独立 sshd 实际配置一致的端口；公开/本机转发端口固定8765。
关闭用户/系统 ssh config、共享连接和 agent，固定严格host key、BatchMode、IdentitiesOnly、
ExitOnForwardFailure、ConnectTimeout10、15秒保活/3次。文件路径支持空格，拒绝UNC、控制字符、引号和SSH展开标记。
参数通过 argv 传入，不经 shell，不自动更改已核验 known_hosts，不请求 shell/PTY。
SSH 失败返回其非零退出码；Ctrl+C 停止前台入口，没有后台重连循环。
保活只检测 SSH 连接，不能证明 WSS relay、USB 固件或手机视频正常。

另一个前台终端由操作者启动账号 relay：`run_relay.ps1 -Mode Run -BindAddress 127.0.0.1 -AccountsFile <本机账号文件> -TlsCert <证书链> -TlsKey <本机TLS私钥>`。
手机 schema2 地址改为 `wss://<云端地址>:8765/stream`，但 TLS 仍终止在 PC，证书 SAN 必须匹配手机访问的云端 IP/域名。
不能继续使用只包含校园网 IP 的旧 leaf。debug APK 信任的测试 CA 可以保留，为云端地址重新签发 leaf；
现有 `prepare_test_tls.py --ca-dir ... --ip <云端IPv4>` 支持 IPv4 换签到新目录，域名证书须由可信签发流程包含 DNS SAN。
CA/服务器私钥始终留在 PC；账号模式不允许 ws 降级，不关闭 CA/主机名/板端公钥验证。
与局域网使用同一份记录协议、suite2 和手机登录流程，路径仍支持显式 `/stream?takeover=1`。
具体服务端限制见 [云中转契约](../doc/cloud_relay_plan.md)。本轮没有部署云端、启动隧道或验证公网视频。
