# Windows PC 部署教程（正式版第一版）

PC 负责账号登录及视频转发。本教程使用 SD 本地身份固件，正常启动不需要开发参数。
证书、SSH、迁移和旧固件的完整操作保留在 [高级部署说明](DEPLOYMENT_ADVANCED.md)。

## 1. 已配置好的电脑：日常启动

按 [板端教程](../board/DEPLOYMENT.md) 上电并接好视频 USB，在 PowerShell 运行：

```powershell
eyepqc check
eyepqc run
```

`check` 应显示 `CONFIG_OK`。看到 `RELAY_READY` 和 `PC_RUNNING` 后，在手机输入账号、密码并连接。
保持窗口打开；停止时先在手机点“停止”，再在 PC 这个窗口按 **Ctrl+C**。
不加 `--dev-usb-bootstrap` 或 `--dev-identity-file`；旧 USB 初始化固件需先升级，不能仅删除参数。

## 2. 全新电脑：安装并创建账号

1. 准备 Windows x64，按交付清单核对安装包 SHA256。升级旧程序前先正常停止旧服务。
2. 运行 `EYEPQC-Setup-1.4.0-rc2.exe`，选择 **Install program only**（只安装程序）。
3. 安装后关闭全部终端，重新打开 PowerShell：

```powershell
eyepqc --version
eyepqc init
eyepqc account add --username viewer
eyepqc account list
```

版本应为 `EYEPQC PC 1.4.0-rc2`。按提示输入两次密码，输入时不显示字符是正常的；没有默认密码。
已有配置不要再 `init`；若提示已有数据，用 `eyepqc config show` 查看，不删除目录重来。
安装器不附送账号、证书、配对文件或 SSH 密钥。材料准备好之前，`check` 报缺文件是正常的。

## 3. 全新电脑：准备连接材料

默认目录为 `%LOCALAPPDATA%\EYEPQC\pc\data`。先完成下表；只升级已有部署时保留原材料和路径。

| 相对 data 的位置 | 谁准备 |
|---|---|
| `private/accounts.json` | 上一节账号命令自动创建 |
| `public/pairing.json` | 板端部署者提供公开公钥/指纹，再按高级说明第 4.1 节生成，地址对应手机实际 WSS 地址 |
| `public/server-chain.pem` | 证书部署者签发，覆盖实际 IP/域名，手机 APK 须信任其 CA |
| `private/server-key.pem` | 与上行证书匹配的 TLS 私钥，只留 PC |
| `private/id_ed25519` | 本 PC 生成专用 SSH 密钥，只交 `.pub` 公钥给服务器部署者 |
| `public/tunnel_known_hosts` | 服务器部署者从可信控制台提供并与 PC 部署者核对的 SSH 服务公钥记录 |

自己从零搭建时，按 [高级说明](DEPLOYMENT_ADVANCED.md) 第 4.1、4.2、4.3 节准备配对、证书及 SSH，
同时完成 [服务器配置](../server/DEPLOYMENT.md) 和 [Android 安装](../mobile/DEPLOYMENT.md)。这些准备需要源码/Python，不是安装器内置功能。
私有文件放入工具创建的受保护目录；不要放宽权限或发给他人。PC 日常运行不需要板端私钥及随机状态文件。
已有身份和配对请复用，不要为升级重建身份；旧测试证书到期时按高级说明续签，并保持手机信任一致。

## 4. 全新电脑：配置串口和公网隧道

在 Windows **设备管理器 → 端口（COM 和 LPT）** 找到视频 USB CDC 端口，它与 CH340 调试串口不同。
把下面 `COM7` 换成实际视频端口。材料已放入默认目录时运行：

```powershell
eyepqc config set serial_port COM7
eyepqc config set tunnel.host 203.0.113.10
eyepqc config set tunnel.ssh_port 22022
eyepqc config set tunnel.enabled true
ssh -V
eyepqc config show
eyepqc check
```

`ssh -V` 找不到命令时，先安装 Windows OpenSSH Client。更换服务器时同步修改实际地址和证书。
材料在其他位置时，按高级说明第 5 节配置实际路径；不要照抄不存在的示例路径。
`check` 成功后按第一节启动。它只检查本机材料，最终以手机能显示视频为准；手机登录后自动获取公开配对信息。

## 5. 管理账号和密码

```powershell
eyepqc account list
eyepqc account add --username user2
eyepqc account passwd --username viewer
eyepqc account delete --username user2 --yes
```

新增、改密时交互输入两次密码，不把密码写进命令；不能删除最后一个账号。
修改后手机停止、PC 按 Ctrl+C，再 `eyepqc run` 才生效。当前一块板卡同时服务一个观看连接。

## 6. 常见问题

| 现象 | 处理方法 |
|---|---|
| `eyepqc` 找不到 | 退出全部终端后重开；仍失败可用 `& "$env:LOCALAPPDATA\EYEPQC\pc\bin\eyepqc.exe" --version` 检查安装 |
| 安装提示材料导入失败 | 取消后重开安装器，选 **Install program only**；按第二、三节配置 |
| `check` 缺文件或无效 | 核对配置路径、配对身份、证书/私钥和文件权限；不要发送私钥内容 |
| relay 端口已占用 | 用 `eyepqc status` 查看，在所属旧服务窗口 Ctrl+C；不要重复启动或盲目杀进程 |
| USB 打不开或超时 | 核对视频 COM 号、USB 线及供电，关闭占用该端口的其他工具 |
| 手机证书错误/握手超时 | 检查证书期限/地址/手机信任、服务器隧道及板卡状态，不关闭证书校验 |
| 板端报 SD 身份/状态错误 | 按板端教程处理，不恢复旧随机状态备份或注入秘密绕过 |

升级前正常停止服务并备份 PC 设置和材料到受保护位置，安装时保留原数据。迁移、续签和回滚见 [高级部署说明](DEPLOYMENT_ADVANCED.md)。
