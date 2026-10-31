# Server 1.0.0-rc1 部署、维护与回滚

本候选只交付源码、固定 systemd 模板、教程及校验清单；**部署执行及验收由用户统一进行**。
本轮没有连接服务器，不代表 Linux/systemd/公网通过。本文 `203.0.113.10` 与 SSH `22022` 为示例，实际值由管理员提供。

## 1. 职责与边界

链路是 Android WSS → 云端 TCP8765 → PC 主动建立的 SSH22022 反向隧道 → PC `127.0.0.1:8765` → USB 板卡。
云端不终止业务 TLS，不存手机密码、账号数据库、TLS 叶私钥、CA 签发私钥、板端身份或视频。
业务证书仍由 PC 提供，SAN 必须匹配公网 IP，Android 信任与它对应的公开 CA；不能关闭证书验证。
本服务只接收 PC 专用 SSH 公钥。服务器独立持有 SSH host key；PC 必须独立核验其指纹。

固定隔离服务是 `eyepqc-tunnel.service`、专用非登录用户 `eyepqc-tunnel` 和 `/etc/eyepqc-tunnel`。
SSH22022 与业务 TCP8765 不替代或修改管理 SSH22。不要覆盖 `/etc/ssh/sshd_config`，不要停止管理服务。
不要将聊天中出现过的密码用作长期凭据；此流程不接受 root 密码文件，不自动 SSH 到任何主机。

## 2. 解包、核对和前置环境

在可信独立新目录解压 `EYEPQC-Server-1.0.0-rc1.zip`，核对发布者提供的 ZIP SHA256 和包内清单。
Linux 在解压目录执行 `sha256sum -c SHA256SUMS.txt`；Windows 用 `Get-FileHash -Algorithm SHA256` 核对下载 ZIP。
清单只能发现变更，必须先从可信渠道取得预期 ZIP 哈希，不能用同一不可信来源的两个文件互证真实性。

包内：`prepare_tunnel.py`、`eyepqc-tunnel.service`、`package_candidate.py`、本教程、两组离线测试、
`manifest.json`、`SHA256SUMS.txt`。没有真正的 `sshd_config`、`authorized_keys` 或任何私钥。
根目录未授予项目统一开源许可；此包不改变自研代码授权，不附 OpenSSH/Python 二进制。

需要 Python 3.10+、systemd Linux、兼容这些固定指令的 OpenSSH，路径为 `/usr/sbin/sshd`、`/usr/bin/getent`，
并有 `/usr/sbin/nologin`。先按发行版官方方式安装/更新 Python 与 OpenSSH Server；不同路径/非 systemd 系统应停止并适配，
不要为通过校验而放宽限制。包不提供自动下载安装器、自动安全组修改或后台服务部署。

在服务器保留已有可用管理会话及云控制台入口，先只读检查：

```sh
python3 --version
/usr/sbin/sshd -V
command -v systemctl
test -x /usr/bin/getent && test -x /usr/sbin/nologin
getent passwd eyepqc-tunnel
getent group eyepqc-tunnel
sudo systemctl status eyepqc-tunnel.service --no-pager
sudo ss -ltnp
```

首次部署预期专用账号/组、目录和单元不存在；若已存在，转到“升级”，不能重复创建或覆盖来源不明的服务。
确认 22022 未被其他服务占用。8765 将由 PC 的专用隧道占用，服务本身不直接提供业务监听。
静态单测可在 Windows 或 Linux 解压目录执行，不需要 root、key、联网：

```sh
python3 -m unittest discover -s tests -v
```

## 3. 准备唯一 PC 专用公钥并生成配置

PC 先按其教程在受保护私有目录准备专用 Ed25519 SSH 身份。只把 `.pub` 复制到受信任的服务器暂存目录，
**不要复制 PC 私钥**。在 PC 独立读出该公钥 SHA256 指纹，通过可信管理渠道与服务器收到的公钥比对。

```powershell
ssh-keygen -lf C:/secure-public/eyepqc-tunnel.pub -E sha256
```

服务器示例暂存父目录是 `/home/operator`，请换成已存在、由可信操作者控制且不允许其他人写入的绝对目录。
公钥输入文件名必须以 `.pub` 结尾。输出目录必须未存在，不放在 `.ssh`、`.git`、`private` 或系统目录。
以下命令从解压目录执行，把指纹占位换成上一步真实独立核对的值（不是密码）：

```sh
python3 prepare_tunnel.py generate --public-key-file /home/operator/eyepqc-tunnel.pub --expected-key-sha256 'SHA256:REPLACE_WITH_VERIFIED_FINGERPRINT' --output-dir /home/operator/eyepqc-bundle
python3 prepare_tunnel.py validate --bundle-dir /home/operator/eyepqc-bundle
```

默认 SSH22022；若确需改端口，用 `--ssh-port`，仅接受 1024..65535 且不能为 8765，不支持管理端口22。
固定配置拒绝多公钥、附加 authorized_keys 选项、修改转发目标/用户/Include/Match；不要手改后跳过校验。
生成出的目录严格只有三个文件，不能把教程/备份塞进去再运行 validate。

## 4. 首次安装（仅用户确认目标后执行）

以下动作会创建专用用户和指定文件。只有确认是全新本项目目标时执行；已有服务走升级流程。
`install` 会覆盖指定文件，所以先执行这些拒绝已有目标的检查，任何失败都停止；不添加 `-f` 或盲目删除旧文件。

```sh
test ! -e /etc/eyepqc-tunnel && test ! -L /etc/eyepqc-tunnel
test ! -e /etc/systemd/system/eyepqc-tunnel.service && test ! -L /etc/systemd/system/eyepqc-tunnel.service
! getent passwd eyepqc-tunnel
! getent group eyepqc-tunnel
```

检查通过后，按顺序执行并检查每条退出码，不使用忽略错误的批量粘贴：

```sh
sudo useradd --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin --password '*' eyepqc-tunnel
sudo install -d -o root -g root -m 0755 /etc/eyepqc-tunnel
sudo install -o root -g root -m 0600 /home/operator/eyepqc-bundle/sshd_config /etc/eyepqc-tunnel/sshd_config
sudo install -o root -g root -m 0644 /home/operator/eyepqc-bundle/authorized_keys /etc/eyepqc-tunnel/authorized_keys
sudo ssh-keygen -t ed25519 -N '' -f /etc/eyepqc-tunnel/ssh_host_ed25519_key
sudo chmod 0600 /etc/eyepqc-tunnel/ssh_host_ed25519_key
sudo install -o root -g root -m 0644 /home/operator/eyepqc-bundle/eyepqc-tunnel.service /etc/systemd/system/eyepqc-tunnel.service
sudo python3 prepare_tunnel.py validate --bundle-dir /home/operator/eyepqc-bundle --linux-sshd-check
```

`*` 是不可用密码，不是登录密码；不能改成锁定 `!`，后者在 `UsePAM no` 下可能连公钥登录也拒绝。
私钥/config 为 root:root 0600；授权公钥0644与目录0755让专用用户可读取但不能改授权。
不复用其他用户、不加 sudo、shell、PTY，也不修改管理 sshd 或其用户。host key 只生成一次，不在升级时重建。

真实 Linux 校验要求 root，检查账户/组/shadow/安装目标及父目录权限，随后执行真实 `sshd -t/-T` 并核对每个有效限制。
缺路径、权限不符、发行版不支持或 platform 不符都会失败。部分发行版需由其包管理/运行机制提供 `/run/sshd`，
应按系统规范处理，不能通过禁用校验绕过。校验不是 systemd 启动、SSH 登录或公网验收。

## 5. 用户启动、端口与 SSH 主机信任

真实 Linux 校验成功后，由用户确认再启动**仅此专用单元**：

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now eyepqc-tunnel.service
sudo systemctl status eyepqc-tunnel.service --no-pager
sudo journalctl -u eyepqc-tunnel.service -n 50 --no-pager
sudo ss -ltnp
sudo ssh-keygen -lf /etc/eyepqc-tunnel/ssh_host_ed25519_key.pub -E sha256
```

服务 `Restart=no`，故障时不后台无限重启。云安全组/系统防火墙由用户在既有规则中明确允许所需 TCP22022 和 TCP8765，
保留现有管理端口与规则；本包不提供 flush/disable 防火墙命令。能访问端口不代表有权使用隧道。
通过独立可信控制台核对上面的 host 公钥指纹。PC 可从网络采集公钥，但必须与该指纹比对后才写入专用 known_hosts；
单独一次 `ssh-keyscan` 不建立可信身份。IPv4非默认端口条目为 `[203.0.113.10]:22022`。

PC 只允许固定反向目标 `0.0.0.0:8765:127.0.0.1:8765`；不要绕过 CLI 改成其他本地目标或 `GatewayPorts yes`。
固定 SSH 用户是 `eyepqc-tunnel`；专用 key 应拒绝 shell、命令、PTY、本地转发、其他远端端口、agent/X11/StreamLocal。
服务端 PermitListen 约束远端监听，不证明授权 PC 的本地目标，所以 PC 自身参数也必须严格保持。

## 6. 日常维护、换 key 与升级

只读检查用 `systemctl status`、`journalctl -u ...`、`ss -ltnp`。先核对进程/端口归属，不杀未知 PID。
服务端日志只应记录 SSH 元数据，不记录视频或业务凭据；提交排错材料先去除不必要个人信息。

升级前，在可信 root 私有备份目录保留现有整个 `/etc/eyepqc-tunnel`（含 host key）、单元、来源包及各自 hash。
备份目录须唯一、0700，备份不得放进源码/Release/公共网盘。本教程不自动替你执行备份或复制私钥。
确认旧环境属于本项目、已核验当前 host 指纹和权限；不复用来源未知的安装。

更新步骤：

1. 手机停止观看、PC 正常 Ctrl+C 停止自有 relay/SSH，记录中断维护窗口。
2. 用新版本工具在新的可信暂存目录重新生成三文件并静态 validate，核对预期 PC 公钥指纹。
3. 备份完成后只停止 `eyepqc-tunnel.service`，不要停止管理 SSH。
4. 仅用新 config/authorized_keys/service替换匹配目标，保持上述 root 所有权和模式；**保留原 host 私钥和 `.pub`**。
5. 用新工具对新 bundle 执行 `--linux-sshd-check`，任何失败保持专用服务停止并回滚；不要强行启动。
6. 通过后 `daemon-reload`、启动专用单元，独立核对 host 指纹不变，再由 PC 重启并按用户表验收。

换 PC key 同样使用新 `.pub` 与独立指纹生成；当前模型只授权一个 key，旧 PC 隧道先正常退出。
不要追加多个 key 或把旧 key 的 options 丢掉。若 host key 本身泄露，属于独立安全事件：吊销旧信任、
生成并通过独立可信渠道重新分发新指纹，不可伪装普通无感升级。

## 7. 回滚与停用

失败时保存新包/hash、脱敏日志和失败退出码，正常停止 PC 及专用服务，不覆盖失败证据。
从自己的受保护备份恢复同一目标的 config/authorized_keys/service及匹配旧工具/bundle，保持 root 权限，
不重建或改变 host key；对旧 bundle 重新执行真实 Linux 校验，再 daemon-reload/启动专用单元。
配置/程序回滚不表示已验证视频，须用户重新确认。

仅需停用时执行 `sudo systemctl disable --now eyepqc-tunnel.service`；不删除账号、host key、配置或备份。
原管理 SSH 保持不变。完全清理属于另一个需核实目标的操作，本教程不提供递归删除命令。

## 8. 用户验收与常见故障

| 现象 | 先查什么 |
|---|---|
| 22022 不监听 | 专用单元 status/journal、真实 sshd -t/-T、路径/权限和端口占用；不改管理 SSH |
| 公钥 Permission denied | PC实际身份/用户是否匹配；服务key指纹、options、账户`*`与文件可读权限；不开放密码认证 |
| SSH通但8765没有 | PC是否正常建立唯一`-R`，转发是否因旧owner/端口占用失败；不再启动第二个隧道 |
| APP TLS错误 | PC叶链、IP SAN、时间与APP CA是否匹配；云端不提供业务TLS，不能在云端随便装证书解决 |
| HTTP/WSS登录拒绝 | PC账号/快照、APP凭据、显式接管流程；服务器不存手机账号 |
| 视频/USB QUERY失败 | 按PC/Board记录真实日志；不把SSH成功当作板端成功 |

验收按同一固定候选记录：实际Linux版本/OpenSSH版本、包hash、真实校验/单元状态、正反key/用户/越权拒绝、
WSS证书与账号拒绝、手机/板端视频、STOP/换钥/断线/持续时长。模板见
[统一验收表](https://github.com/fantZach/EYEPQC/blob/main/doc/deployment/ACCEPTANCE.md)。
未测项留空/写未执行；本候选的 `user_acceptance=pending`、Linux/systemd/public验证false不手工改成软件测试通过。

## 9. 维护者本机重新打包

从仓库根执行（输出父目录先已存在，文件必须不存在）：

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s server/tests -v
& ./.venv/Scripts/python.exe server/package_candidate.py --output build/releases/v1.1.0-rc1/EYEPQC-Server-1.0.0-rc1.zip
```

工具仅固定白名单，不递归带入身边的运行配置或key，不覆盖已有ZIP，不联网/装服务。
打包不代替许可证权利确认、真实Linux、部署或公网验收。
