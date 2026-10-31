# Server：Ubuntu 公网中转部署

这是项目正式第一版的服务器操作教程。服务器组件程序版本仍为 `1.0.0-rc1`，交付源码和配置生成工具；本文不会替你连接或修改现有服务器。
**已有本项目服务的服务器不要重复执行首次安装**，直接查看第 6 节及[高级升级说明](DEPLOYMENT_ADVANCED.md#6-日常维护换-key-与升级)。

## 1. 先分清三个端口

| 端口 | 用途 | 连接方 |
|---|---|---|
| TCP 22 | 服务器原有管理 SSH，保持原配置 | 管理员 |
| TCP 22022 | EYEPQC 专用 SSH 反向隧道 | Windows PC |
| TCP 8765 | 手机访问的视频 WSS 入口 | Android 手机 |

示例公网 IP 为 `203.0.113.10`。PC 主动连接 22022，将服务器 8765 转发回 PC；云端不解密视频，也不保存手机账号或业务 TLS 私钥。
请在云控制台安全组中放行 TCP 22022、8765，保留管理 SSH 的现有规则；若系统另启用防火墙，也须允许这两个端口，不关闭整个防火墙。

## 2. 管理员准备材料

在开始前准备好以下内容，发布包**不包含**实际密钥或账号：

- 一台有公网 IP 的 Ubuntu 22.04/24.04 服务器，以及已有可用的 SSH/sudo 管理权限。
- Server 交付 ZIP 和通过可信渠道获得的 ZIP SHA256。
- Windows PC 管理员生成的**专用 Ed25519 隧道公钥** `eyepqc-tunnel.pub`，及其独立核对的 SHA256 指纹。PC 私钥留在 PC，不上传服务器。

PC 管理员可用 `ssh-keygen -lf 公钥文件.pub -E sha256` 查看公钥指纹；密钥准备见 [PC 教程](https://github.com/fantZach/EYEPQC/blob/main/pc/DEPLOYMENT.md)。
服务器管理账号与手机观看账号是两套账号，手机账号由 PC 管理。

## 3. 全新 Ubuntu 安装环境并生成配置

通过云控制台或已有管理 SSH 登录，保留这个管理窗口。以下命令在服务器执行；每段成功后再继续，报错时停止。

```sh
sudo apt-get update
sudo apt-get install python3 openssh-server unzip
python3 --version
sudo ss -ltnp
```

确认 Python 至少为 3.10，并且 22022 未被其他程序占用。首次部署时，以下检查都必须成功；否则转高级升级流程，不覆盖旧文件：

```sh
test ! -e /etc/eyepqc-tunnel && test ! -L /etc/eyepqc-tunnel
test ! -e /etc/systemd/system/eyepqc-tunnel.service && test ! -L /etc/systemd/system/eyepqc-tunnel.service
! getent passwd eyepqc-tunnel
! getent group eyepqc-tunnel
test ! -e /opt/eyepqc-staging-1 && test ! -L /opt/eyepqc-staging-1
sudo install -d -o root -g root -m 0700 /opt/eyepqc-staging-1
```

用云控制台文件传输或已有管理 SSH，把 ZIP 和 `eyepqc-tunnel.pub` 上传到服务器，管理员将它们放到上述暂存目录。
下面假设分别命名为 `/opt/eyepqc-staging-1/server.zip` 和 `/opt/eyepqc-staging-1/eyepqc-tunnel.pub`。
不要上传任何私钥；暂存目录只允许可信管理员写入。

```sh
sudo -i
cd /opt/eyepqc-staging-1
sha256sum server.zip
```

核对输出与负责人提供的 ZIP 哈希一致后再解压：

```sh
unzip server.zip -d source
cd /opt/eyepqc-staging-1/source
sha256sum -c SHA256SUMS.txt
ssh-keygen -lf /opt/eyepqc-staging-1/eyepqc-tunnel.pub -E sha256
```

将下面 `SHA256:REPLACE_WITH_VERIFIED_FINGERPRINT` 替换为 **PC 管理员独立提供并已核对一致**的真实公钥指纹：

```sh
python3 prepare_tunnel.py generate --public-key-file /opt/eyepqc-staging-1/eyepqc-tunnel.pub --expected-key-sha256 'SHA256:REPLACE_WITH_VERIFIED_FINGERPRINT' --output-dir /opt/eyepqc-staging-1/bundle
python3 prepare_tunnel.py validate --bundle-dir /opt/eyepqc-staging-1/bundle
```

看到校验成功后继续。生成目录必须是新的，不手改生成的三个文件。

## 4. 安装并启动独立隧道服务

仍在上一步 root 管理窗口执行。这只创建 EYEPQC 专用账号和服务，不修改管理 SSH22：

```sh
useradd --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin --password '*' eyepqc-tunnel
install -d -o root -g root -m 0755 /etc/eyepqc-tunnel
install -o root -g root -m 0600 /opt/eyepqc-staging-1/bundle/sshd_config /etc/eyepqc-tunnel/sshd_config
install -o root -g root -m 0644 /opt/eyepqc-staging-1/bundle/authorized_keys /etc/eyepqc-tunnel/authorized_keys
ssh-keygen -t ed25519 -N '' -f /etc/eyepqc-tunnel/ssh_host_ed25519_key
chmod 0600 /etc/eyepqc-tunnel/ssh_host_ed25519_key
install -o root -g root -m 0644 /opt/eyepqc-staging-1/bundle/eyepqc-tunnel.service /etc/systemd/system/eyepqc-tunnel.service
python3 prepare_tunnel.py validate --bundle-dir /opt/eyepqc-staging-1/bundle --linux-sshd-check
```

只有最后一条真实 Linux 检查成功后才启动；失败先看[高级说明](DEPLOYMENT_ADVANCED.md#4-首次安装仅用户确认目标后执行)，不跳过校验。
`'*'` 表示不可用密码，不是给用户登录的密码，也不要替换为锁定标记 `!`。

```sh
systemctl daemon-reload
systemctl enable --now eyepqc-tunnel.service
systemctl status eyepqc-tunnel.service --no-pager
ss -ltnp
ssh-keygen -lf /etc/eyepqc-tunnel/ssh_host_ed25519_key.pub -E sha256
cat /etc/eyepqc-tunnel/ssh_host_ed25519_key.pub
```

应看到专用服务 active、22022 监听。**此时 8765 尚未监听是正常的**，它要等 PC 建立隧道。
最后两条只输出服务器 SSH **公钥**及指纹；经可信管理渠道交给 PC 管理员，制作 `[203.0.113.10]:22022` 的专用 known_hosts 条目。
不把单独一次 `ssh-keyscan` 当作身份验证。

## 5. 让 PC 接入，再让手机连接

PC 按 [PC 教程](https://github.com/fantZach/EYEPQC/blob/main/pc/DEPLOYMENT.md) 设置服务器 IP、SSH 端口 22022、专用私钥和已核验的 known_hosts，然后运行 `eyepqc run`。
服务器再次执行 `ss -ltnp`，应看到隧道创建的 `0.0.0.0:8765`。
手机使用 `wss://203.0.113.10:8765/stream` 和 **PC 创建的观看账号**连接。

业务 TLS 证书由 PC 提供，必须匹配公网 IP；手机须信任对应 CA。不要把 PC TLS 私钥或板卡私钥放到服务器。
PC 必须保持运行，服务器单独启动不能提供视频。

## 6. 日常检查与常见问题

```sh
sudo systemctl status eyepqc-tunnel.service --no-pager
sudo journalctl -u eyepqc-tunnel.service -n 50 --no-pager
sudo ss -ltnp
```

| 现象 | 先检查 |
|---|---|
| 22022 无监听 | 专用服务日志、安装校验、端口占用 |
| PC 提示 SSH 公钥拒绝 | 专用用户是否为 `eyepqc-tunnel`，公钥与 PC 私钥是否对应 |
| 22022 正常但没有 8765 | PC 是否运行且唯一隧道建立成功，避免重复启动 |
| 手机证书失败 | PC 的证书地址、期限与手机 CA；服务器不终止业务 TLS |
| 手机账号错误 | PC 账号数据库，与服务器管理账号无关 |

需要停用时用 `sudo systemctl disable --now eyepqc-tunnel.service`；不要停止管理 SSH，也不删除密钥或配置。
升级、备份、换密钥、回滚和完整验收见[高级说明](DEPLOYMENT_ADVANCED.md)。首次手机视频、换钥和稳定性由操作者实际验证并记录。
