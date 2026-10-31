# EYEPQC PC 1.4.0 · 项目 v1.1.0

本包适用于 Windows x64，包含 CLI、当前用户安装器、[详细部署教程](DEPLOYMENT.md) 和完整第三方许可。
本包用于项目 v1.1.0 的当前可用基线；用户已确认 SD 模式连接及首次连接问题修复。其他故障/长稳与生产安全不因此全部通过；既有 v1.0.0 资产不变。

## 新电脑

1. 核对发布清单 SHA256，运行 `EYEPQC-Setup-1.4.0.exe`，默认选择 **Install program only**。
   无需先提供六份运行材料；不自动生成账号、证书、SSH/板端身份，不启动服务。
2. 退出全部 Windows Terminal/PowerShell 窗口后重新打开；`eyepqc --version` 应为 `1.4.0`。
3. 没有旧设置时执行：

```powershell
eyepqc init
eyepqc account add --username viewer
eyepqc config show
```

`init` 只创建空受保护目录与本地设置，隧道默认关闭；首个密码隐藏输入两次。
已有 settings/data 时拒绝覆盖。缺材料的 `check/run` 仍失败，不是可直接登录的公共服务包。
真实材料的来源、示例公网 IP `203.0.113.10`（须替换为实际地址）、独立部署 CA、APK 信任、SSH host key 核对，
均按 [DEPLOYMENT.md](DEPLOYMENT.md) 准备。证书工具需要完整源码与开发机依赖，不是 EXE 内嵌签发服务。

## 已有环境、账号与启停

安装器的显式导入模式接受可信旧配置 JSON；留空读取当前用户设置，仍严格校验六份完整材料。
默认程序-only升级保留全部现有设置/数据，不会因不完整材料阻挡程序升级。
卸载保留 settings/data；安装只修改它拥有的当前用户 PATH，不修改系统 PATH。

```powershell
eyepqc check
eyepqc account list
eyepqc account passwd --username viewer
eyepqc status
```

账号另有 `add` / `delete --username <名称> --yes`，不能删除最后一个账号；
运行服务使用启动时快照，账号变更后正常 Ctrl+C 再启动生效。

只有材料和匹配板端已准备好才启动。新增 **SD 本地身份**固件（`G6_SD_IDENTITY` / `--g6-sd-identity`）
在 SD 保存固定私钥和可更新随机状态，PC 不需要板端私钥文件，也不注入 seed：

```powershell
eyepqc run
```

必须先按板端教程准备该固件与 SD 材料，并核对公开 pairing；旧 USB 初始化固件不能仅通过删参数切换。
该模式保持 suite2，不代表板端/断电验收完成，也不声明生产安全；初始材料准备者仍须可信，不能回滚旧随机状态。
普通 `run` 已支持直接转发，不需要因这一模式升级 PC 运行时代码。

原 `G6_DEV_USB_BOOTSTRAP` 固件继续使用以下显式开发初始化命令：

```powershell
eyepqc config set serial_port COM7
eyepqc run --dev-usb-bootstrap
```

从1.4.0起，默认身份路径为当前用户 `LOCALAPPDATA/EYEPQC/pc/data/private/board-test-identity.bin`。
可选 `--dev-identity-file <受保护文件>` 仍支持；普通 `run` 不读取身份，默认文件不会自动生成。
READY状态只查询核pin；只有WAIT真正装载时才读取身份，并保留原权限/长度/pin检查及失败拒绝。

`COM7` 只是示例，须确认视频 USB CDC，不是调试串口。
上述 USB 开发身份必须是操作者受保护且与 pairing 匹配的 1632 字节 ML-KEM-512 测试私钥；包内不带，此旧模式不写入 SD。
已通过其他方式准备好的普通 G6 使用 `eyepqc run`；不能混用开发初始化 profile。
看到 RELAY_READY 不是视频验收，先手机停止再 PC Ctrl+C；不要抢占串口、盲杀进程或自动重试初始化。

## 保留限制

- 用户已反馈当前 SD 基线首次连接问题修复；本次打包未新增板卡、手机或公网实测。
- 本地 USB 开发初始化是明文，PC 知道板端身份/seed；不是对恶意 PC 的生产安全或前向保密。
- PC 程序仍未商业代码签名，不承诺杀毒软件无告警；不关闭防护或弱化 TLS。
- 密码、账号库、配对、TLS/SSH/板端私钥、CA 私钥及 seed 均不随包分发。
- 保留 `THIRD_PARTY_NOTICES.md` 与 `licenses/`；项目自研部分未新增统一开源许可。
