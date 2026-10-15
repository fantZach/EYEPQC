# Server 实际部署：124.70.38.245

2026-10-15 用户提供实例并明确授权直接连接、部署 server 服务。
实际实例欢迎信息为 Huawei Cloud，Ubuntu24.04.4 LTS/aarch64，内存3385MiB；不是此前建议规格的购买证明。
首次SSH22主机身份按用户“直接连接”授权采用TOFU，固定已观察的Ed25519公钥，保持StrictHostKeyChecking=yes。
这不是云控制台独立核验，不将ssh-keyscan本身作为可信身份来源。

## 后续：真实板卡经公网WSS短测

2026-10-15约13:12～13:15（本机Asia/Shanghai时间），主聊天独占硬件。
只读JTAG枚举见APU/双Cortex-A9/xc7z020；COM4短时只读未捕获文本，不据此推断当前应用。
`verify_software.py build/vitis/g6_account_ephemeral_20261014_2`通过75项应用文件哈希、BSP查表和ARM启动检查。
随后复用prepare_mobile.py，JTAG易失装载已验证G6固件并注入开发身份/新seed，未写SD/Flash；
新公开身份导出到 `board/output/mobile_identity_cloud_20261015_1`，pin与公网pairing一致。
视频CDC枚举为COM7（03FD:7020），COM4仍为调试串口。

PC使用本轮TLS/独立账号启动真实relay（只绑定127.0.0.1:8765），并以专用key/固定host key启动cloud_tunnel.py。
JVM LiveProbe --account经 `wss://124.70.38.245:8765/stream` 完成suite2真实板卡握手、认证START、
逐帧AES-GCM认证和ImageIO JPEG解码；TLS校验保持启用，无模拟USB。

| 窗口 | 认证解码帧数 | 有效视频跨度 | 帧率 | 最大帧间隔 |
| --- | --- | --- | --- | --- |
| 首次连接，要求30秒 | 1420 | 30.0251542秒 | 47.2603734fps | 0.0713588秒 |
| STOP后重新连接，要求10秒 | 474 | 10.0086845秒 | 47.2589580fps | 0.0469004秒 |

两轮分辨率640×480，客户端退出码0、result.json均PASS；首尾JPEG共4张通过独立Pillow verify及SHA256对照。
原始本机证据（ignored，含真实相机图片，不上传云端或Git）：

- `data/captures/cloud_board_20261015_1/{result.json,first.jpg,last.jpg}`。
- `data/captures/cloud_board_20261015_2/{result.json,first.jpg,last.jpg}`。
- `tmp/cloud_wss_20261015_1/real_board_{relay_1,tunnel_1,probe_1,probe_2}.log`。

首轮首/尾JPEG SHA256分别为
`f472b756c00b5c233fea71cccf093a2d49d2469079eaf9d520d1fa80080b6029`、
`a9d66ec82db114cbf6ce6eca38f8aa95f9af54372a00b5d957757f54e892531e`；
重连首/尾分别为
`ba5bdb34c2f83930980103facdd0e4f422ee08bc6d0bdb9ae8409434f5b5a328`、
`d4a7c701015d8f38824aff8600ee508ee3447cdc40d78cb3329d8d90caea4fb5`。

relay两轮均code1000、stop_forwarded=1、STOP_DRAIN quiet、error=none、queue_peak=4（上限64）；
网络记录/字节/整会话时长分别为11378/16081474/30.922秒、3812/5427225/13.656秒。
按首轮PC应用层发送字节/整会话时长计算平均4.1605Mbit/s，含握手/清理、不含TLS/SSH/TCP开销；
当前场景平均低于10Mbit/s，不能保证峰值、复杂场景或移动网络表现。没有测摄像到显示的端到端延迟。

两次JVM探针已退出，PC relay和SSH隧道保持运行等待手机，当前无探针占用观看会话。
手机下一步导入本轮 `tmp/cloud_wss_20261015_1/public/pairing.json`，账号viewer，
密码在本机受限 `private/login.txt`（与旧局域网密码不同，不通过聊天传递）。
现有0.6 debug APK使用同一测试CA，不需因为公网IP重装；应关闭Wi-Fi、使用移动数据确认异网视频与换钥。

边界：这是同一Windows主机上的JVM经公网服务器往返，不是Android异网/屏幕FPS，也不是完整G8/G9；
只测短连接和主动STOP重连，未验证半小时自动换钥、长时间、断网/慢消费者恢复。
旧局域网QueueFull失败仍保留。本轮无需新代码；依Ponytail复用既有脚本、协议和客户端。
板端长期身份/seed仍由可信开发PC通过JTAG注入，SD仍是G0自检，不是生产安全或SD独立视频启动。

## 安全组放行后：最新验证

用户回复“放行了”后，PC专用账号/密钥通过公网SSH2222完成认证，原cloud_tunnel.py成功建立固定-R。
从本机连接云端124.70.38.245:8765，1459字节随机合成负载经真实SSH原样到达PC127.0.0.1:8765，
云端入口收到32字节SHA256回复且一致，测试窗口0.031秒。这是单次字节往返，不是视频延迟或带宽测量。
独立探针结果在ignored `tmp/cloud_124_70_38_245_20261015/tcp_route_result_1.json`。

实际SSH五项权限拒绝通过，结果为同目录 `ssh_restrictions_3.json`：

- session/exec被CHANNEL_OPEN_FAILURE拒绝，没有执行远程命令；Windows客户端返回4294967295。
- 远端额外监听8766请求被拒绝，exit255。
- root用户名、未授权另一把key均被拒绝，exit255；不尝试密码或重复猜测。
- 本地-L转发的实际通道请求被administratively prohibited拒绝，未返回目标SSH banner。

第一次探针对session拒绝文本断言过窄，真实OpenSSH MaxSessions0默认可标作connect failed；
核对[官方serverloop实现](https://github.com/openssh/openssh-portable/blob/master/serverloop.c)后改为核对CHANNEL_OPEN_FAILURE。
第二次在负测夹具key的严格ACL检查处中止，未放宽权限；换用与正测相同生成方式的新负测key后完整通过。
前两份FAIL JSON保留，不作为服务策略错误或删除的失败证据。

## 公网WSS材料及模拟USB验证

本机 `tmp/cloud_wss_20261015_1` 已准备匹配云IP的证书、schema2配对JSON、独立viewer测试账号；
原局域网材料未修改，密码仅在本机受限ACL的 `private/login.txt`，不发到聊天/仓库/云端。
复用现有debug CA，DER SHA256仍为263c8c06420a2b72726d93c746766d3efd8040fe6d711af49f240ebbc1b4dc8b；
云地址叶证书DER SHA256为37cd77d6eadea6c2a5d142a515893605bbb9d12bfb7778bd2b912ea6774b7dba，
到期2026-10-22 13:04:02（Asia/Shanghai）。当前0.6 debug APK若仍信任同一CA，不因新IP需要重打包。
板卡身份pin沿用原公开身份a14a7f6fe9e862b90e66e413e4d0fcdbfc63e1b8bc0c0ff31e11324482927928。
配置端点为wss://124.70.38.245:8765/stream，JSON只有version/endpoint/public_key_hex/public_key_sha256。

通过真实公网SSH/TCP，PC临时启动原Relay与模拟CDC，完成：
不可信CA拒绝、错误主机名拒绝、错密码HTTP401、正确证书与账号WebSocket升级成功、模拟CDC释放五项PASS。
最终结果 `tmp/cloud_wss_20261015_1/cloud_wss_result_4.json`；关闭日志code1000/errornone。
前三次夹具清理等待基于忙轮询下的短sleep次数，实际等待不足，未断言通过；FAIL结果保留。
最终夹具使用与实际串口相符的20ms读取等待和单调时间截止，清理0.109秒内完成，没有改Relay运行时代码。

没有打开真实USB、执行ML-KEM业务握手、发送视频或在Android真机运行。
这是真实云网络/TLS/账号+模拟CDC验证，不是此前软件回环，也不是完整G9。
测试后临时本机监听/探针和前台SSH隧道均停止，未留下模拟服务；云端独立systemd服务仍按部署启用。
8765公开监听随授权PC的-R建立/结束而出现/释放，不是systemd本身常驻的业务监听。

## 已完成的远端变更

- 首次用用户提供的root凭据在SSH密码提示交互登录；密码未放命令行、部署文件或Git，没有修改root密码。
- 只读预检确认原SSH22正常，2222/8765无监听，专用账号及项目目标路径不存在。
- 上传5份公开配置/校验文件至 `/home/eyepqc-deploy-20261015`，逐文件SHA256核对通过。
  该目录包含bundle三份文件及tools中的校验脚本和同版service模板，未上传客户端私钥、CA/TLS私钥、业务密钥或账号材料。
- 新增 `eyepqc-tunnel` 非root专用用户，无home和可用密码，shell为nologin；配置公钥只授权本机专用隧道key。
- 安装 `/etc/eyepqc-tunnel/sshd_config`、root:root0644的受限authorized_keys，生成独立Ed25519 host key。
- 安装 `/etc/systemd/system/eyepqc-tunnel.service`，daemon-reload并enable/start，实际状态 `active`。
- 独立daemon监听 `0.0.0.0:2222`；原SSH22监听仍存在，没有修改其配置或重启管理服务。
- 云端持有独立SSH host key；TLS/账号仍在PC，云端不运行USB、视频解密或JPEG保存。

## 实际验证

真实Linux校验入口成功执行，安装账号/父目录/权限/文件等值校验与 `/usr/sbin/sshd -t/-T` 全部通过。
server仅允许remote forwarding到监听0.0.0.0:8765，禁shell/session、PTY、local/agent/X11/StreamLocal；
本轮确认的是有效配置，实际正确/错误key与禁止操作的运行验证尚未完成。
服务日志显示Server listening on0.0.0.0 port2222；云内127.0.0.1:2222返回正确OpenSSH banner。
UFW inactive，iptables INPUT/FORWARD/OUTPUT策略为ACCEPT；没有改变主机防火墙、代理或云安全组。

已固定的公开身份（不含任何私钥）：

- 管理SSH22 TOFU指纹：`SHA256:SF8hykiRNa4coyUquZVm2T+3SQMuWG4z+m4kKWwf3Ew`。
- 独立隧道SSH2222指纹：`SHA256:Y2OipXgDeQOWgzq3GUQJu1+19clCkaBRxZ7nk0f84/M`，从已建立管理会话读取并固定。
- 客户端专用公钥指纹：`SHA256:rHp54yOy37IiDSw004SEoQahDj3rcPAxKe2Uu+GBdAM`。

安装bundle SHA256：

| 文件 | SHA256 |
| --- | --- |
| sshd_config | 0804980029f4e82f9ecda6f2fddf4b3b53565c5342e9af208ef8d89dc949c24a |
| authorized_keys | b77e144b1a2bda0716813d04d120662a9bae981a399cbaf7ce73d0c0bd380ce9 |
| service | 319e26007c6855ef7b95e2fa71341054674eb07f095ce5475bcb9019124340f3 |

## 放行前公网连接失败（历史，保留）

PC用实际cloud_tunnel.py/专用key/严格known_hosts连接公网2222，两次均在握手前被关闭，exit255。
sshd日志未见对应外网连接；同期云端eth0上12秒仅筛选目的2222的TCP SYN捕获为0，未捕获payload。
可确认该次流量未被观察到达实例监听；不能单凭此区分云安全组、Mihomo/TUN或中间网络路径原因。
最初普通TcpClient.Connect成功不代表实际SSH可达，已用banner/真实SSH失败证据纠正此边界。

已请用户核对/放行安全组入站TCP2222和TCP8765，保留SSH22，不开放全部端口。
TCP8765仅在授权PC建立-R后才出现监听；daemon active不意味着手机WSS或反向隧道已就绪。
当时无反向隧道/WSS云地址证书；放行后的阶段结果见上方最新验证。手机公网视频和G9仍未通过，未操作板卡/JTAG/SD/COM。
实际key授权及禁止操作需公网可达后补测；原QueueFull和P2P失败证据不被覆盖。

## 恢复与安全

已安装服务按用户授权保持运行并设置开机启用。回退可先stop/disable此独立unit；
不会删除原管理SSH或其他服务。保留暂存bundle供安装等值核对，未清理或覆盖用户数据。
本机专用私钥位于ignored的受限ACL目录，固定host key文件及公开bundle也位于ignored tmp；不提交凭据。
已建议用户更换聊天中披露的root密码，但没有擅自执行更改，避免导致管理入口失联。
