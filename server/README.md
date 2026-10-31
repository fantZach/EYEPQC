# Server 子项目：受限 OpenSSH TCP 中转

## 下一版候选与部署教程

Server `1.0.0-rc1` 提供独立源码包，完整的新环境部署、维护、换 key、升级/回滚见
[DEPLOYMENT.md](DEPLOYMENT.md)。用户统一执行部署及验收，打包不会连接云端或改动现有服务。
`package_candidate.py` 只导出固定源码/模板/教程/测试及脱敏清单，默认 `user_acceptance=pending`；
不含真实授权文件、运行 config 或 host 私钥。以下 v1.0.0/旧部署记录保持历史范围。

## v1.0.0 项目发布入口

Server 随项目以源码、配置生成器及 systemd 模板发布，不附服务器密码、SSH 私钥、
生产 `authorized_keys` 或运行态配置。安装时须自行准备专用公钥、独立核验 host key，
并按下文真实执行 Linux 校验；仓库发布不会替你安装、启动或更新云端服务。

2026-10-21 发布前复核：16 项离线单测通过，未连接云端、未变更运行服务。
下列 2026-10-15 部署记录是历史证据，不表示本次发布已重新确认服务器在线状态或完成 G9。

本目录提供独立 Linux sshd 配置生成/校验及 systemd 模板；冻结接口见
[公网中转契约](../doc/cloud_relay_plan.md)。初始代码准备阶段未部署，当前状态以下列更新为准。

2026-10-15部署更新：用户授权后，独立服务已安装在124.70.38.245并处于active，真实Linux安装与sshd校验通过；
安全组放行后，实际专用key授权/固定反向隧道、合成TCP往返及五项SSH越权拒绝通过；
公网TLS/账号拒绝与正确登录（模拟CDC）通过。临时PC探针/隧道已停止，云端服务仍启用。
真实手机/板卡视频、持续吞吐和G9未通过。
下文保留代码准备/部署流程，实际证据及TOFU信任边界见 [部署记录](../report/server_deployment_20261015.md)。

```text
Android WSS → 云端 TCP8765 → SSH -R → Windows PC 127.0.0.1:8765 → USB Board
                          PC 主动连接云端 SSH2222
```

云端不处理手机账号或密码，不终止业务 TLS，不运行 ML-KEM/AES 或解码/保存 JPEG。
云端持有独立 SSH host key（传输层服务器身份）；手机登录、接管、TLS 私钥、业务密钥均在 PC。
手机证书验证必须匹配云端域名/IP，不能使用只有校园网地址 SAN 的旧叶证书。

## 本地生成与静态校验

需要 Python 3.10+，无新增依赖。输入只接受单条普通 Ed25519 `.pub` 文件，不读取私钥。
在持有专用 PC 公钥的可信机器执行 `ssh-keygen -lf <公钥.pub> -E sha256`，独立核对它
属于该 PC 专用隧道密钥，再传入指纹。指纹检查不能替代操作者对 PC 身份的确认。
不要把私钥或密码发进聊天。

```powershell
python server/prepare_tunnel.py generate --public-key-file C:/secure-public/eyepqc-tunnel.pub --expected-key-sha256 SHA256:<已核验指纹> --output-dir C:/staging/eyepqc-bundle
python server/prepare_tunnel.py validate --bundle-dir C:/staging/eyepqc-bundle
python -m unittest discover -s server/tests -v
```

`<已核验指纹>` 必须替换。父目录须已存在，输出目录须不存在；拒绝相对路径、点路径、
符号链接/junction、`.ssh`、`.git`、`private` 和系统目录。不覆盖文件或创建父目录。
POSIX 生成目录为 0700，三份文件为 0600；Windows 不声称 POSIX mode 等同 NTFS ACL，
操作者须选可信 ACL 的暂存目录。不要在不可信用户可并发改写的共享目录中以 root 运行工具。

输出为 `sshd_config`、`authorized_keys`、`eyepqc-tunnel.service`。
默认 SSH2222，`--ssh-port` 可改为 1024..65535 中除 8765 外的端口。
SSH22/低端口、其他用户名/转发端口/安装路径都不提供配置入口。
固定用户 `eyepqc-tunnel`、安装路径 `/etc/eyepqc-tunnel`、sshd `/usr/sbin/sshd`。
其他发行版路径须另行复核模板与校验，不能放宽当前检查。

配置没有 Include/Match，不引用或改写 `/etc/ssh/sshd_config`。仅允许上述用户及唯一公钥：
`AuthenticationMethods publickey`，禁密码、键盘交互、hostbased、CA key 和外部授权命令；
`GatewayPorts clientspecified`、`AllowTcpForwarding remote`、`PermitListen 0.0.0.0:8765`，
以及 key 级 `restrict,port-forwarding,permitlisten=...`。
`MaxSessions 0` 禁 shell/exec/subsystem 会话且保留 `ssh -N` 转发；另有 ForceCommand，
并禁 PTY/agent/X11/StreamLocal/tunnel/user RC。监听限制不能验证授权 PC 的远端目标，
PC 入口必须固定 `-R 0.0.0.0:8765:127.0.0.1:8765`，见 PC 子项目。

## 新环境部署流程（须另行授权执行）

先确认已授权 Linux 实例、发行版 OpenSSH 支持所有指令，以及 `/usr/sbin/sshd`、
`/usr/bin/getent`、`/usr/sbin/nologin` 存在。不改现有管理 SSH22、防火墙/安全组，不停启
管理服务。下面仅供未来部署，用户名/组已存在时应停止，不复用来源不明的现有账号。

```sh
sudo useradd --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin --password '*' eyepqc-tunnel
sudo install -d -o root -g root -m 0755 /etc/eyepqc-tunnel
sudo install -o root -g root -m 0600 /home/operator/eyepqc-bundle/sshd_config /etc/eyepqc-tunnel/sshd_config
sudo install -o root -g root -m 0644 /home/operator/eyepqc-bundle/authorized_keys /etc/eyepqc-tunnel/authorized_keys
sudo ssh-keygen -t ed25519 -N '' -f /etc/eyepqc-tunnel/ssh_host_ed25519_key
sudo chmod 0600 /etc/eyepqc-tunnel/ssh_host_ed25519_key
sudo install -o root -g root -m 0644 /home/operator/eyepqc-bundle/eyepqc-tunnel.service /etc/systemd/system/eyepqc-tunnel.service
sudo python3 server/prepare_tunnel.py validate --bundle-dir /home/operator/eyepqc-bundle --linux-sshd-check
```

安装目标须不存在或已核实属于本项目；`install` 会覆盖指定文件，host key 只首次生成，
不在重部署覆盖，保留原指纹。`/home/operator/...` 是示例绝对路径。
用户无 sudo、可登录 shell 或可用密码；不用 `passwd -l`/`!` shadow 值：在 `UsePAM no`
下 Linux OpenSSH 锁定账号检查可能同时拒绝公钥。要求不可匹配密码的 `*`，并由 sshd
明确禁止密码认证。公钥 `authorized_keys` 部署为 root:root 0644，父目录 0755，允许
sshd 以目标用户读取；该用户不能改写授权文件。host key/config 为 root:root 0600。

Linux 校验核对账户、shadow 标记、安装文件/权限，然后执行真实 `sshd -t` 和
`sshd -T -C user=eyepqc-tunnel,host=localhost,addr=127.0.0.1`，逐项核对有效配置。
缺 sshd、平台不符、未安装、权限不符或不支持指令均返回非零，不跳过或降级。
这仍不证明真实登录、systemd 启动或转发成功。部分发行版需要包管理建立的 `/run/sshd`
或其他 privilege-separation 目录；按发行版核查并让 `sshd -t` 真实通过，本单元不接管
管理 SSH 的共享运行目录。

校验后再由操作者授权执行 `systemctl daemon-reload` 与
`systemctl enable --now eyepqc-tunnel.service`。单元先执行 sshd `-t`，独立 foreground
daemon，`Restart=no`，不后台反复重连/重启。按已确认需求放通 TCP2222/TCP8765，保持
原管理入口，不添加全局规则。通过可信控制台核对 SSH host key 指纹，PC 才建立专用
known_hosts；未经核对的 ssh-keyscan 结果不是信任依据。

## 验收边界

单测覆盖参数/公钥/路径拒绝、配置与 service 篡改拒绝、不覆盖、指纹错误及 CLI 区分
静态检查与 Linux 执行。链接标记与 `-T` 解析使用 mock/合成文本，不声称实际创建 Windows
链接、实际 Linux sshd 或公网隧道验收。依据：
[OpenSSH sshd_config](https://man.openbsd.org/sshd_config)、
[authorized_keys](https://man.openbsd.org/sshd#AUTHORIZED_KEYS_FILE_FORMAT)、
[`-T` 输出实现](https://github.com/openssh/openssh-portable/blob/master/servconf.c)。

公网仍需：端口可达、正确/错误公钥及用户登录、shell/PTY/local/其他 remote/agent/X11/
StreamLocal 拒绝、正确 TCP8765 隧道、WSS SAN/账号拒绝、suite2 认证视频、STOP/换钥/
断线重连/吞吐。配置生成与仓库回归不能将 M18/G9 标为完成。
