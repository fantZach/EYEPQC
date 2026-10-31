# Windows PC 部署教程（1.4.0-rc2 候选）

本文是从新电脑开始的操作顺序。软件检查由开发方执行，安装、板卡、手机、网络和最终验收由操作者统一记录。
候选包不宣称正式验收通过，也不改变当前开发态安全模型。

## 1. 准备与职责

- Windows x64；程序为当前用户安装，无需管理员权限。安装目录：`%LOCALAPPDATA%\EYEPQC\pc\bin`。
- 公网中转需要 Windows OpenSSH Client，运行 `ssh -V` 确认。只做程序安装或局域网且关闭隧道时不强制已有 SSH 材料。
- 视频 USB CDC 和 COM4 调试串口不是同一接口。`COM7` 只是历史示例，必须从设备管理器确认本机视频端口。
- 本 PC 负责 TLS 和账号，服务器只透明转发 TCP；板卡不直接联网。
- 真实密码、TLS/SSH/板端私钥由部署者私下保管。包内没有默认账号、现成私钥、运行配对或服务器管理密码。

从候选交付 ZIP 解压，保留 `THIRD_PARTY_NOTICES.md` 和 `licenses/`，核对清单中的 SHA256：

```powershell
Get-FileHash ./EYEPQC-Setup-1.4.0-rc2.exe -Algorithm SHA256
Get-FileHash ./eyepqc-1.4.0-rc2.exe -Algorithm SHA256
```

程序未商业代码签名，不保证杀毒软件无告警。不要关闭安全软件、修改全局执行策略或运行来源不明的下载器。

## 2. 安装程序，不要求先有密钥

先在手机停止观看，再在旧 PC 服务窗口 Ctrl+C，避免替换运行中的文件或占用串口。
运行 `EYEPQC-Setup-1.4.0-rc2.exe`，默认选择 **Install program only**。
此模式不读/导入/重置运行材料，不启动服务，已有设置即使不完整也原样保留。

若已有可信旧配置，可选择 **Import existing trusted runtime materials as well**，
选旧配置 JSON；该页留空表示使用当前用户设置。导入仍逐项验证六份材料与私有 ACL，
缺少/损坏/不匹配会拒绝，不生成替代身份。不要把账号数据库或私钥发给其他人来凑齐文件。

安装完成，退出全部 Windows Terminal 窗口后重新打开，确认用户 PATH：

```powershell
Get-Command eyepqc
eyepqc --version
eyepqc config show
```

版本应为 `EYEPQC PC 1.4.0-rc2`。若终端仍未刷新，可直接调用
`& "$env:LOCALAPPDATA/EYEPQC/pc/bin/eyepqc.exe" --version`，不要删除其他 PATH 项。

自动化安装默认同样只装程序；显式迁移参数为 `/SOURCECONFIG=<可信旧配置绝对路径>`，
显式验证/复用当前设置为 `/IMPORTCURRENT=1`。这些参数不能用于密码或私钥内容。

## 3. 新环境初始化（已有设置跳过）

没有旧配置/材料的新电脑执行：

```powershell
eyepqc init
eyepqc config show
eyepqc account add --username viewer
eyepqc account list
```

`init` 只创建空的 `data/private`、`data/public` 与无秘密的设置，隧道默认关闭。
private ACL 只允许当前用户和 SYSTEM，初始化失败不放宽 ACL。
随后 `account add` 在隐藏提示中输入两次新密码，即可创建首个数据库；没有默认密码。
若 settings 或 data 已存在，`init` 拒绝而非覆盖，请使用原配置维护，不要删除数据来强行重试。
此时 `eyepqc check` **预期失败**：证书、配对等尚未准备；程序安装完成不等于可播放。

若你有完整可信旧配置且尚未初始化，也可改走迁移：

```powershell
eyepqc install-data --config C:/secure-deploy/old-config.json
```

此命令需要六项完整源文件及 OpenSSH 本地解析，不连接服务器。不要先 `init` 再把一套旧身份覆盖到已有 data；
迁移、手动配置是二选一的首次部署路线。

## 4. 六份材料从哪里来

```powershell
$Data = "$env:LOCALAPPDATA/EYEPQC/pc/data"
$Private = "$Data/private"
$Public = "$Data/public"
```

| 文件 | 准备者与来源 | 必须核对 |
|---|---|---|
| `private/accounts.json` | 第 3 步账号命令创建，或完整迁移原账号库 | 加盐 scrypt，不是明文密码；文件及父目录私有 ACL |
| `public/pairing.json` | 板端部署者导出的 800 字节公钥及 SHA256，结合本次真实 WSS 地址生成 schema2 | 与同一板端身份匹配；无 token/password；不能任意换公钥 |
| `public/server-chain.pem` | 部署者的 TLS 证书链，或受控开发 CA 签发 | SAN 覆盖手机实际访问的公网域名/IP，链完整，当前有效 |
| `private/server-key.pem` | 上一行证书对应的本机 TLS 私钥 | 与证书匹配；只存私有目录，不发给中转服务器/手机 |
| `private/id_ed25519` | 本机生成的专用 SSH 隧道密钥 | 仅公钥交给服务器管理员，私钥受保护，不复用 root 管理密钥 |
| `public/tunnel_known_hosts` | 从服务器可信控制台取得并独立核对的隧道 sshd host 公钥 | 匹配真实主机及 SSH 端口；不能仅凭 ssh-keyscan 建立信任 |

局域网且 `tunnel.enabled=false` 时，`run/check` 不要求后两份 SSH 文件。
`install-data` 是完整六文件迁移工具，不是四文件局域网安装器。

### 4.1 公开配对文件

开发源码环境需要 Python 3.12+ 与项目依赖，以下从仓库根目录运行。
由板端部署流程提供一个目录，内含**公开**的 `public.bin` 和 `public.sha256`。
使用者先从独立可信渠道核对指纹，不能从同一未知下载链接同时取得公钥和“可信”指纹。

全新部署尚无身份时，按 [板端教程](https://github.com/fantZach/EYEPQC/blob/main/board/DEPLOYMENT.md) 选择与实际固件匹配的身份准备路线；
已有受信身份不因升级无意重建。两条路线的公开 `public/` 目录均可用于下一条 `--identity-dir`：

- **SD 本地身份 `G6_SD_IDENTITY`**：固定私钥和可更新随机状态只部署到 SD；PC 运行只需公开配对资料，
  不把板端私钥复制到 `$Private`，不通过 USB 注入 seed。不要复制旧运行状态来“恢复”随机状态。
- **原 USB 初始化 `G6_DEV_USB_BOOTSTRAP`**：按原 `prepare_dev_identity.py` 路线，将
  `private/board-test-identity.bin` 单独复制到受保护的 `$Private/board-test-identity.bin`；
  此路线不把秘密写入 SD，仍要求可信 PC 提供开发身份和 seed。

两者都不能把私钥放到 public/、配对 JSON 或候选压缩包。SD 路线接受物理读卡风险，不等于生产密钥存储；
复用 PC 曾持有的旧身份不能消除历史副本，初始材料准备者也必须可信。

以下使用示例公网 IP `203.0.113.10`；部署时替换为管理员提供的实际地址，以下命令只生成本地材料，不连接该服务器。
只有更换实例时才将地址同步替换为新 IP 和证书 SAN：

```powershell
& ./.venv/Scripts/python.exe pc/src/host/prepare_pairing.py --identity-dir C:/secure-public/board-public --endpoint wss://203.0.113.10:8765/stream --config-file "$Public/pairing.json"
```

不加 `--token-file`，不使用旧 schema1。输出文件须不存在，不直接覆盖旧身份。
手机会通过 HTTPS 账号认证自动获取这份公开 schema2；首次信任和身份变更仍须按移动端说明确认。

### 4.2 为当前公网 IP 创建独立部署 CA 与 TLS 证书

当前无域名，采用部署者自有 CA，并在 Android 发布变体构建时通过 `-TrustCaFile` 显式信任其**公开**证书。
这不是沿用旧 debug CA，也不依赖旧 APK 的 30 天调试信任。工具不会生成账号、密码、板端身份或修改服务。
任意新建 CA 不会自动被旧 APK 信任，必须按 [移动端教程](https://github.com/fantZach/EYEPQC/blob/main/mobile/DEPLOYMENT.md) 重建和签名。
CA 私钥不能打入 APK；云服务器透明中转，TLS 证书终止点仍在 PC。

在[完整源码](https://github.com/fantZach/EYEPQC)根目录准备开发机依赖；候选程序 ZIP 不包含一个可独立运行的裸证书脚本，
须取得该源码内完整 `pc/src/host/`、`pc/requirements*.txt` 及本机 Python 环境：

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r pc/requirements-deployment.txt
$Issuer = "$env:LOCALAPPDATA/EYEPQC/pc/issuer-20261031"
& ./.venv/Scripts/python.exe pc/src/host/prepare_deployment_tls.py --ip 203.0.113.10 --output-dir "$Issuer"
[System.IO.File]::Copy("$Issuer/private/server-key.pem", "$Private/server-key.pem", $false)
[System.IO.File]::Copy("$Issuer/public/server-chain.pem", "$Public/server-chain.pem", $false)
```

父目录需存在；`issuer-20261031` 必须是全新目录，已有时改一个新名称而非覆盖。
复制同样拒绝已有目标；已有 TLS 部署应先保存受保护备份并计划切换，不在运行服务时替换。
默认 CA 有效 3650 天、叶证书 365 天，可通过 `--ca-days`/`--leaf-days` 缩短；
新叶证到期不超过 CA，CA 用途/签名/公私钥匹配/私有 ACL 均校验。
命令只显示公开指纹和到期时间，`prepared.json` 同样不含秘密。独立核对并保管 `public/ca.pem` 指纹。
把 `$Issuer/public/ca.pem` 提供给 Android 的 `-TrustCaFile`，**只传公开证书**，不传 `private/`。

原 CA 私钥只留签发机；到期前显式用原 CA 在新目录续签叶证，避免每次无意更换手机信任根：

```powershell
$Renewed = "$env:LOCALAPPDATA/EYEPQC/pc/leaf-renewal-20271001"
& ./.venv/Scripts/python.exe pc/src/host/prepare_deployment_tls.py --ip 203.0.113.10 --ca-dir "$Issuer" --output-dir "$Renewed" --leaf-days 365
```

续签目录不复制 CA 私钥；新 IP 必须重新签发匹配 SAN 的叶证。过期/不匹配/不适用的 CA 会拒绝。
CA 轮换需重新构建/更新 Android 信任配置并由操作者验收，不能关闭 TLS 地址/期限校验。
旧 `prepare_test_tls.py` 只用于历史短期调试（还会生成随机账号和 login.txt），不是本教程默认部署工具。
旧 APK 测试 CA 于 2026-11-12 16:59:03 UTC 到期，不能以旧包永久使用或关闭验证。

### 4.3 专用 SSH 公钥及服务器 host key

在已初始化的受保护私有目录生成专用密钥：

```powershell
ssh-keygen -t ed25519 -f "$Private/id_ed25519"
ssh-keygen -lf "$Private/id_ed25519.pub" -E sha256
```

当前无人值守隧道不读取密码或 agent，所以在交互式 passphrase 提示中按两次回车留空；
这只适用于受保护的专用私钥，不适用于管理 SSH 密钥。已有目标文件时停止，不能确认覆盖。
将 `.pub` 与其独立核对的 SHA256 指纹交给服务器部署者，私钥留在 PC。
从服务器控制台核对专用 `/etc/eyepqc-tunnel/ssh_host_ed25519_key.pub` 指纹，
按 `[实际主机]:22022 ssh-ed25519 公钥base64` 格式保存 `tunnel_known_hosts`；若端口不是 22022，应一致修改。
服务器生成、安装、授权与端口限制见 [服务器教程](https://github.com/fantZach/EYEPQC/blob/main/server/DEPLOYMENT.md)。

## 5. 配置并离线检查

默认文件位置已指向第 4 步目录；若材料位于其他受保护路径，逐个显式设置，不编辑 EXE：

```powershell
eyepqc config set serial_port COM7
eyepqc config set accounts_file C:/secure-deploy/private/accounts.json
eyepqc config set pairing_file C:/secure-deploy/public/pairing.json
eyepqc config set tls_cert C:/secure-deploy/public/server-chain.pem
eyepqc config set tls_key C:/secure-deploy/private/server-key.pem
eyepqc config set tunnel.host 203.0.113.10
eyepqc config set tunnel.ssh_port 22022
eyepqc config set tunnel.identity_file C:/secure-deploy/private/id_ed25519
eyepqc config set tunnel.known_hosts C:/secure-deploy/public/tunnel_known_hosts
eyepqc config set tunnel.enabled true
eyepqc config show
eyepqc check
```

上例是“材料外置”的完整示范，不要把已正确指向用户 data 的路径改为不存在的示例。
公网部署需地址、证书 SAN、手机 endpoint 和 host key 四者匹配。
局域网可以保持 `tunnel.enabled false`，但账号模式仍用 WSS；不能把运行失败改成明文 WS。
`CONFIG_OK offline_only=true` 只证明本地账号/配对/TLS格式与配置可读，**不证明**证书链被手机信任、
SAN/有效期满足本次手机地址、host key 经独立核对、公网端口可达、板卡 READY 或视频成功。

## 6. 启动与正常停止

确认旧服务已停止，先 `eyepqc status` 查看端口所有者；它不读密钥、不访问 USB，也不证明所有者就是本程序。
不要根据端口号直接批量杀进程。串口/板端镜像准备按 [板端教程](https://github.com/fantZach/EYEPQC/blob/main/board/DEPLOYMENT.md)。

新增 **SD 本地身份**固件须先由板端流程写入匹配的 BOOT 和身份/随机状态材料，并完成状态读写检查；
构建参数为 `--g6-sd-identity`，不是原 USB bootstrap 镜像。PC 使用公开 pairing、账号及 TLS/SSH 配置即可：

```powershell
eyepqc run
```

普通 `run` 不读取板端身份、不生成板端 seed，也不发送 EYBS QUERY/DATA；板端启动/持久化失败不能由 PC 开关绕过。
保留原有运行材料和备份，本步骤不自动删除旧 PC 身份。不得把 SD 运行状态的旧备份恢复到卡上继续运行。
新固件尚需操作者完成断电、重连、换钥与视频验收；PC 启动成功本身不证明板卡就绪。

以下命令仅供**原 SD USB 开发初始化**固件使用，需要匹配的 1632 字节测试身份文件，位置及 ACL 由板端部署者准备，
其公钥必须匹配 pairing；不会由 PC 安装包创建或写入 SD：

```powershell
eyepqc run --dev-usb-bootstrap
```

从 1.4.0-rc2 起，只需显式给出 `--dev-usb-bootstrap`，默认身份路径是当前用户 `LOCALAPPDATA/EYEPQC/pc/data/private/board-test-identity.bin`。
若私钥在其他受保护位置，可额外指定 `--dev-identity-file <文件>`；旧完整命令继续兼容，单独给文件参数而没有开发开关仍拒绝。
默认路径不受当前工作目录/EXE位置影响，不搜索其他目录或自动创建身份。视频 COM 口仍须显式设置。
程序只在状态、pin、ACL 和材料通过后发送本地明文开发初始化，得到 READY 后才开启监听/隧道。
PC 因而知道板端身份与 seed，不宣称针对恶意 PC 的生产端到端安全或前向保密。
SD 本地身份或其他单独准备好的普通 G6 固件使用 `eyepqc run`；不要混用初始化 profile。

看到 `RELAY_READY` 与 `PC_RUNNING` 只表示本地就绪/SSH正在连接；手机再输入账号密码并连接。
结束时手机先停止观看，PC 窗口 Ctrl+C；仅退出本次创建的 relay 和 SSH 子进程。
客户端停止、故障、重连/换钥、帧率与实际时间由操作者在 [统一验收表](https://github.com/fantZach/EYEPQC/blob/main/doc/deployment/ACCEPTANCE.md) 记录。

## 7. 账号、升级和回滚

```powershell
eyepqc account list
eyepqc account add --username second
eyepqc account passwd --username viewer
eyepqc account delete --username second --yes
```

密码交互输入两次，命令行不含密码。不能删除最后一个账号，损坏数据库不会被静默重建。
服务使用启动时账号快照，修改后正常停止再启动生效，不会偷偷踢掉正在工作的进程。

升级前停止观看和 PC 服务，将 `settings.json` 与 `data/` 备份到自己受保护的本机目录或加密离线介质，
并保留当前 EXE/安装包及 SHA256。备份包含私钥和密码派生值，不上传云盘/Issue。
新版本选程序-only即可保留原设置和账号。卸载只删除程序及安装器拥有的 PATH 项，保留 settings/data。
回滚同样先正常停止，再安装已核验的旧安装包；如果新版本曾改变配置格式，先查对应迁移说明，
不得把旧配置盲写覆盖后续维护的账号或身份。1.4.0-rc2 仍使用配置 version=1、schema2/suite2。

## 8. 常见故障与交付边界

| 现象 | 安全排查顺序 |
|---|---|
| `eyepqc` 找不到 | 重开全部终端，检查 `Get-Command` 与用户 PATH，再用安装目录绝对 EXE 路径确认 |
| 首次安装没有六份文件 | 选程序-only；`init` 建空目录，然后按本教程准备材料，缺材料不能启动 |
| `init` 拒绝已有数据 | `config show` 识别既有配置；不要删除目录、强制覆盖或重置身份 |
| `check` 缺文件/证书错误 | 核对已配置路径、对应公私钥、配对格式与私有 ACL；不要把私钥内容贴日志 |
| relay 8765 已占用 | 查所有者，正常停止所属旧实例；不重复启动、不盲杀进程 |
| SSH255/host key拒绝 | 控制台核对host key、专用公钥、端口/服务器限制；不使用StrictHostKeyChecking=no |
| 手机 TLS/握手超时 | 检查实际地址/SAN/有效期/可信CA、账号、隧道及板端状态，分层保留脱敏日志 |
| 连接异常 | 先保留脱敏错误和时间再排查；此前首次连接问题已由用户确认修复，本次未新增实测 |
| FAULT | 保存元数据并停止；按板端教程恢复，不绕过安全状态或偷偷JTAG恢复 |

本轮只交付候选软件与教程，未替操作者验收板端、手机、公网或生产安全；EXE/安装器依然未商业签名。
