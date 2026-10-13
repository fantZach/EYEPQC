# 上板前 PC 测试 TLS 与账号准备

2026-10-14 任务。只准备文件，未启动/恢复任何服务，未操作板卡、串口、JTAG 或 SD。

## 已准备材料

目录：`tmp/preboard_20261014_r1/`，整个目录由 Git 忽略。

- `public/ca.pem`：专用 debug 测试 CA，可移交 Android 内置到 debug APK。
- `public/server-chain.pem`：服务器 leaf + CA 公开证书链。
- `public/pairing.json`：schema2 四项公开配置，endpoint 为 `wss://10.179.236.247:8765/stream`，无 token/密码。
- `private/ca-key.pem`、`private/server-key.pem`：CA/服务器私钥，仅本机。
- `private/accounts.json`：viewer 的加盐 scrypt 哈希。
- `private/login.txt`：用户名 viewer 与随机 32 字节熵、URL-safe 编码的密码，仅供用户在本机读取。
- `prepared.json`：完成状态、路径、公开摘要和 ACL 校验结果，无密码/私钥。

私有目录 ACL 已移除继承，仅当前用户 SID 与 SYSTEM FullControl；目录及每个私有文件均逐个校验。
初次 Windows PowerShell 模块自动加载失败时停止在生成秘密之前；改用 .NET ACL API 后完成保护。
只移除了本次自己创建且核实为空的失败目录，未覆盖原 CA、证书或其他材料。

CA 证书 DER SHA-256 fingerprint：
`263c8c06420a2b72726d93c746766d3efd8040fe6d711af49f240ebbc1b4dc8b`。

CA 有效期 30 天，leaf 7 天（含 5 分钟起始时钟容差）。证书记录的到期时间：
CA `2026-11-12 16:59:03 UTC`，leaf `2026-10-20 16:59:03 UTC`。
leaf SAN 为 IP `10.179.236.247`、IP `127.0.0.1`、DNS `localhost`，用途仅 TLS serverAuth，不能签发证书。
物理以太网 IPv4 已只读核对为 `10.179.236.247`，未使用 Mihomo 地址。

公开身份从 `tmp/mobile_pairing/public` 读取；800 字节公钥与原配对 JSON 及
`board/output/m09/public.bin` 逐字节一致。公钥 SHA-256：
`a14a7f6fe9e862b90e66e413e4d0fcdbfc63e1b8bc0c0ff31e11324482927928`。
未读取板端 SK，未生成新板卡身份，也未重新 provision。

## 重现与换 IP

以下命令必须选择不存在的新输出目录，工具拒绝覆盖；先完成 private ACL 才生成秘密：

```powershell
& ./.venv/Scripts/python.exe pc/src/host/prepare_test_tls.py --output-dir tmp/preboard_20261014_r1 --identity-dir tmp/mobile_pairing/public
# 原目录已经存在，上面的命令现在会拒绝；这是预期行为。
# 换 IP 时复用原 CA，只读原 CA 私钥，输出新 leaf/key/config 到另一个新目录。
& ./.venv/Scripts/python.exe pc/src/host/prepare_test_tls.py --ca-dir tmp/preboard_20261014_r1 --output-dir tmp/preboard_new_ip_r2 --identity-dir tmp/mobile_pairing/public --ip <新的物理IPv4>
```

复用 CA 不替换原 CA/key，不复制 CA 私钥到新目录。新目录有独立随机测试账号；
若保留原账号，可在启动时继续指定原 `private/accounts.json`，不用修改它。
CA 已过期/不足一天、CA/key 不匹配、身份摘要不匹配或 ACL 校验失败均停止。
工具 stdout 仅输出 prepared 状态、路径和公开摘要。

## 等协调者授权后启动的命令

当前保持停服，下面仅保存命令：

```powershell
& ./pc/run_relay.ps1 -Mode Run -BindAddress 10.179.236.247 -AccountsFile tmp/preboard_20261014_r1/private/accounts.json -TlsCert tmp/preboard_20261014_r1/public/server-chain.pem -TlsKey tmp/preboard_20261014_r1/private/server-key.pem 2>&1 | Tee-Object -FilePath tmp/preboard_20261014_r1/relay.log -Append
```

手机导入公开 schema2，用户名 viewer；密码在本机 private/login.txt，不公开传输或打印。
Android 专用 CA 只放 debug 资源，保留主机名校验、系统信任和板卡公钥 pin；release 不内置本 CA。
若后续开启公开文件下载，HTTP 根目录必须精确为 `public/`，不能服务含 private 的父目录。
调试私钥一旦泄露需更换测试 CA/leaf，不能把本套材料当生产部署。

## 验证边界

新增 2 项离线测试通过：SAN、CA/leaf BasicConstraints/KeyUsage/EKU、有效期、真实 Windows ACL、
随机密码账号可验证、public/summary 不含密码或私钥、既有输出拒绝覆盖、换 IP 保留原 CA/文件、
错误 CA 拒绝、正确 CA 可完成 TLS 握手。TLS 使用 MemoryBIO，不监听网络端口。
ACL 失败注入与坏公钥摘要均在生成密钥/凭据前停止。
原四项 pre-commit hook 保留，仅提交 PC 工具、PC 测试与本报告。

另已完成本轮真实准备材料的本机探针：仅绑定 `127.0.0.1` 的系统分配临时端口，
Relay 使用模拟 CDC，本轮实际 CA/server chain/key/accounts。随机密码仅在 Python 进程内
读取 private/login.txt，不进入命令行或输出。可信 CA + 实际账号 WSS 正向连接及模拟控制往返通过；
错误密码返回 401 且不打开模拟 CDC，错误 CA 与错误 server_hostname 均被 TLS 拒绝。
finally 关闭 server 并等待结束，确认临时监听已关闭。工具输出只含公开连接统计与通过标记。
探针未操作正式 8765、实际 USB、板卡或 SD，也不是手机/临时 KEM 业务握手验收。

未执行正式 WSS 服务、手机、USB 或实板握手；到期后需重新签发，证书准备不等于上板验收通过。
