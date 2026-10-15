# Server 实际部署：124.70.38.245

2026-10-15 用户提供实例并明确授权直接连接、部署 server 服务。
实际实例欢迎信息为 Huawei Cloud，Ubuntu24.04.4 LTS/aarch64，内存3385MiB；不是此前建议规格的购买证明。
首次SSH22主机身份按用户“直接连接”授权采用TOFU，固定已观察的Ed25519公钥，保持StrictHostKeyChecking=yes。
这不是云控制台独立核验，不将ssh-keyscan本身作为可信身份来源。

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

## 公网连接未完成

PC用实际cloud_tunnel.py/专用key/严格known_hosts连接公网2222，两次均在握手前被关闭，exit255。
sshd日志未见对应外网连接；同期云端eth0上12秒仅筛选目的2222的TCP SYN捕获为0，未捕获payload。
可确认该次流量未被观察到达实例监听；不能单凭此区分云安全组、Mihomo/TUN或中间网络路径原因。
最初普通TcpClient.Connect成功不代表实际SSH可达，已用banner/真实SSH失败证据纠正此边界。

已请用户核对/放行安全组入站TCP2222和TCP8765，保留SSH22，不开放全部端口。
TCP8765仅在授权PC建立-R后才出现监听；daemon active不意味着手机WSS或反向隧道已就绪。
当前无反向隧道、WSS云地址证书、手机公网视频或G9通过声明，没有操作板卡/JTAG/SD/COM。
实际key授权及禁止操作需公网可达后补测；原QueueFull和P2P失败证据不被覆盖。

## 恢复与安全

已安装服务按用户授权保持运行并设置开机启用。回退可先stop/disable此独立unit；
不会删除原管理SSH或其他服务。保留暂存bundle供安装等值核对，未清理或覆盖用户数据。
本机专用私钥位于ignored的受限ACL目录，固定host key文件及公开bundle也位于ignored tmp；不提交凭据。
已建议用户更换聊天中披露的root密码，但没有擅自执行更改，避免导致管理入口失联。
