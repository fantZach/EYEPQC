# Server 云 TCP 中转软件交付（2026-10-14）

按 `doc/cloud_relay_plan.md` 冻结契约完成最小独立 OpenSSH server 子项目。
只修改 `server/` 和本报告；未操作硬件/云账户/服务/代理，未启动任何网络探针，
未读取 `tmp/private`、ICE 凭据或任何实际私钥。未新增业务 WSS/KEM 后台。

## 所属文件

- `server/prepare_tunnel.py`：纯标准库生成与静态校验；显式 Linux 安装校验入口。
- `server/eyepqc-tunnel.service`：独立 sshd，先 `-t`、前台执行、`Restart=no`。
- `server/tests/test_prepare_tunnel.py`：16 个定向软件测试。
- `server/README.md`：生成/安装说明、权限与账号细节、真实验收边界。
- `report/server_cloud_20261014.md`：本报告。

默认 SSH2222，公开 IPv4 TCP8765；专用用户 `eyepqc-tunnel`，只有一把已核对
SHA256 指纹的 Ed25519 公钥。固定受限 `authorized_keys` 和独立 `/etc/eyepqc-tunnel`
安装路径。没有 Include/Match，不改已有管理 SSH22。
`GatewayPorts clientspecified`、`AllowTcpForwarding remote`、`PermitListen 0.0.0.0:8765`；
禁止 shell/exec/subsystem/PTY/agent/X11/StreamLocal/local forwarding 与其他监听地址/端口。
配置/服务/公钥约束篡改，危险用户/端口/路径、错误指纹均拒绝。现有输出目录不覆盖。

Linux 实际校验检查专用账户/独立组、不可用 `*` shadow 标记、安装路径无链接、
root 所有权及最小权限，核对已安装文件，再执行真实 `/usr/sbin/sshd -t/-T`。
缺平台/sshd/权限或有效配置不符均非零退出，不降低限制以通过测试。
生成工具不安装、不创建系统用户、不生成 host key、不启动服务。

业务 TLS 在 PC 终止；云端无手机密码处理、业务密钥或 JPEG 解码/落盘。
云端自己的 SSH host key 是必要传输层身份，不是业务 TLS/KEM 密钥。
公钥指纹需独立确认属于正确 PC；server 监听限制不能替代 PC 对 SSH -R 目标的固定。

## 当前宿主验证

- `.venv/Scripts/python.exe -m unittest discover -s server/tests -v`：16/16 PASS。
  使用合成公开测试 key，不是部署授权 key。
- 原 `.githooks/pre-commit` 原样运行：PASS（exit 0）。
  M00 10 tests、M10 PC vectors/parity/Finished/replay/rekey/zeroize、M12 2 tests、G5 1 test。
- 最后复跑 server 16 tests、`py_compile` 和五份所属文件行尾空白检查：PASS。
- 当前 Windows 宿主 `Get-Command sshd` 未找到 sshd；没有实际 Linux `sshd -t/-T`，
  没有 systemd 启动、真实 SSH 登录/隧道或公网验收。
- 链接拒绝测试用 mock 标记；`-T` 解析测试用合成文本，包括指令缺失/重复/限制变宽拒绝。
  这些软件测试不冒充真实 Linux server。
- `-T` 输出解析按 OpenSSH 官方源码核对大小写与 IPv4 ListenAddress 带端口格式：
  [servconf.c](https://github.com/openssh/openssh-portable/blob/master/servconf.c)。

## 提交与剩余门禁

按主聊天最新协调，四端共享 Git index，**本聊天未 stage/commit**；由主聊天最终统一提交。
没有撤销、清理或改写其他端文件/index/提交。

尚需已授权 Linux 实例上实际安装/`sshd -t/-T`/systemd，以及正确和错误 key/用户、
所有被禁转发/会话类型、正确 TCP8765 反向隧道的实测；随后核验 host key、手机 WSS SAN/
账号拒绝、suite2 视频、STOP/换钥/断线重连/吞吐。M18/G9 保持未验收。
未实现新业务后台、自动部署或自动重连；本次交付仅代码和软件证据。
