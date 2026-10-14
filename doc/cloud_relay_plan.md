# 公网服务器中转第一版契约

2026-10-14 用户停止优先推进 P2P，要求先完成各端代码，并单开 server 聊天和文件夹。
采用最小平台方案：OpenSSH 反向 TCP 隧道，不新增云端视频解码、密码协议或账号后台。
P2P 代码和失败证据保留，但当前不继续运行其探针。

## 拓扑与职责

```text
Board ⇄ USB ⇄ Windows PC WSS relay（127.0.0.1:8765）
                        ⇅ PC 主动建立 SSH -R
                  云端 TCP 监听 0.0.0.0:8765
                        ⇅ Android 主动连接 WSS
                  Android suite2 / ML-KEM / AES-GCM
```

- `server/`：独立 OpenSSH server 配置/生成或校验工具、Linux service 模板、部署说明与定向测试。
- `pc/`：复用现有 relay，新增 Windows 反向隧道入口、严格 SSH host key 检查、超时/保活和定向测试。
- `mobile/`：复用 schema2 `wss://<云端地址>:8765/stream`、用户名密码登录、显式接管及 suite2；补充兼容测试/说明，不引入 SSH/WebRTC。
- `board/`：USB/suite2 不改变，复核现有接口及离线回归；不为新增 server 复制协议或修改密码核。
- 主聊天：共享契约、steps/总说明与跨端联测。各端聊天仅编辑所属文件夹及独立报告，不操作硬件、运行服务或云账户。

## 冻结参数与安全边界

1. 手机 URL 路径仍为 `/stream` / `/stream?takeover=1`；消息仍是一条完整 USB 二进制记录，没有新包头。
2. 默认云端公开 TCP8765 通过 `-R 0.0.0.0:8765:127.0.0.1:8765` 转到 PC WSS。PC relay 默认只监听回环。
3. 隧道 PC 使用专用 SSH 用户 `eyepqc-tunnel` 和本机私钥，不用 root/密码，不上传板端身份、种子或 TLS 私钥。
4. 为避免修改已有云端管理 SSH 配置，server 第一版提供独立 sshd 配置和 service，默认 SSH TCP2222。
   可在实际确认校园网端口可达后改 SSH 监听端口；不绕过网络管理规则，不自动更改现有 SSH22。
5. 云端 sshd 使用 pubkey-only，AllowUsers 限定隧道用户，`GatewayPorts clientspecified`、`AllowTcpForwarding remote`、
   `PermitListen 0.0.0.0:8765`，禁止 shell/PTY、agent/X11 和 StreamLocal forwarding。
   用户/公钥/host key/路径校验和最小权限设置由 server 工具与说明覆盖；不自动全局开放转发。
6. PC OpenSSH 必须 `StrictHostKeyChecking=yes`、独立已核验 known_hosts、`BatchMode=yes`、`IdentitiesOnly=yes`、
   `ExitOnForwardFailure=yes`、ConnectTimeout10、ServerAliveInterval15、ServerAliveCountMax3。不信任未经核对的 ssh-keyscan 结果。
7. WSS/TLS 实际终止在 PC，不在云端。服务端证书 SAN 必须匹配手机使用的云端 IP/域名，不能仍用只含校园网 IP 的旧证书。
   调试阶段可复用手机0.6已信任的专用测试 CA 为云端地址重新签叶证书；CA/TLS私钥保留 PC。
8. viewer 的 scrypt 账号、接管/owner fencing、USB 清理和有界队列仍在 PC；SSH 公钥是 PC 上行授权，不替代手机登录。
9. 不自动后台重连或接管账号：第一版隧道失败明确退出，用户/协调者检查后重启；不遗留静默失效进程。
10. 云端/隧道不做业务 ML-KEM/AES、JPEG 解码或落盘。当前开发态 PC/JTAG能接触身份/种子，仍不得宣称生产安全或对恶意PC保密。

## 软件验证与实机门禁

本轮先完成各端代码、参数拒绝/失败/清理测试及软件回环；SSH参数/配置生成检查不冒充Linux sshd执行或公网实测。
必须保留局域网路径和已有APP兼容。公网部署另需用户提供已购实例的公网地址、系统和本机SSH配置位置，不在聊天发送密码/私钥。
后续按 TCP2222可达→核验host key→实际受限隧道→WSS证书/账号拒绝→suite2握手→认证视频→STOP/换钥/断线重连/吞吐推进。
M18/G9 未完成前不标记公网可用；本次服务器方案不抹除既有QueueFull或P2P失败证据。
