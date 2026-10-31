# SD 固定身份与持久随机状态

2026-10-31 用户选择：固定 ML-KEM 身份私钥与随机状态放在 SD；SD 被拿走、复制或恢复旧快照不在本次威胁模型内。验收仍由用户完成。

## 使用边界

此模式取消日常运行 PC 经 USB/JTAG 注入私钥和 seed，手机仍执行现有 schema2/suite2 握手，服务器仍只中转。固定的是身份密钥；临时 ML-KEM 与 AES-GCM 业务密钥继续在新连接和换钥时更新。

这是独立的 SD 软件配置，不是 `G6_PRODUCTION` 熵源/受保护密钥服务，不使用帧数、时间戳或它们的哈希冒充随机熵。
首次配置环境必须可信：它生成或导入私钥并生成初始随机状态，可能保留副本；确定性状态推进不会使已知初始状态的配置者失去推算能力。
复用旧身份能保留手机 pin，但不能撤销旧 PC 对该私钥的了解。初次手机配对仍须信任 HTTPS 配置服务，或通过独立可信渠道核对完整公钥指纹。

## 卡上文件与故障规则

卡根目录除 `BOOT.BIN` 外，需要以下私有文件；它们不得进入 Git、日志、公开配对 JSON 或发布 ZIP。

| 文件 | 内容 |
|---|---|
| `EYEKEY.BIN` | 精确 1632 字节 ML-KEM-512 身份私钥 |
| `EYERNG0.BIN` | 随机状态槽 0 |
| `EYERNG1.BIN` | 随机状态槽 1 |

状态槽各 80 字节：`EYERNG01`（8 字节）、大端 64 位代号、32 字节秘密状态、前 48 字节的 SHA256。
初始化时两槽为相同的第 0 代状态；该秘密由配置端操作系统随机源生成，与身份密钥生成输入独立。

随机数只在握手等需要时生成，视频逐帧加密不写 SD。状态推进必须先写入、同步并重开读回验证，然后才允许使用本次输出。
任一槽缺失、损坏、关系不合法，或写入/同步/读回失败，均停止安全会话，不退回旧 seed、USB 初始化或其他配置。
断电中断写入可能需要人工恢复并重新配置，不能自动用旧槽继续运行。

文件同步和读回依赖实际 SD 控制器的实现，不能证明任意时刻断电都持久保存；软件无法检测整卡旧快照回滚。
已核对 AMD xilffs 的 `CTRL_SYNC` 仅返回成功；适配层另加最多一秒的主机 CMD/DATA 空闲与 DAT0 释放检查，然后由状态层重开读回。
这仍不是卡内缓存强制落盘命令，也不是任意断电情况下的持久性保证。
因此不能复制一份运行卡给另一块板同时使用，也不能把历史随机状态备份恢复成可继续运行的卡。

## 部署与验收

### 离线准备材料

已有部署默认复用旧身份，避免无故更换手机 pin。操作步骤、两种身份来源和核对清单见
[三份 SD 私有文件](../board/SD_PRIVATE_FILES.md)。
在用户自己的可信 PowerShell 中从仓库根目录执行；工具环境可能受 Codex AppData 重定向影响，不能把工具内路径检查等同于用户终端配置。
以下只准备本地新目录，不写 SD。输出目录的父目录必须已存在，目标目录必须不存在。

```powershell
$Prepared = Join-Path $env:LOCALAPPDATA 'EYEPQC/sd-identity-1'
$Existing = Join-Path $env:LOCALAPPDATA 'EYEPQC/pc/data/private/board-test-identity.bin'
& ./.venv/Scripts/python.exe board/prj/prepare_sd_identity.py --output "$Prepared" --identity-file "$Existing"
```

只有全新部署才省略 `--identity-file`，生成新身份；这会改变公钥指纹，不能用于绕过已有 pin 校验。
必须退出 0 并输出 `SD_IDENTITY_PREPARED`；失败留下的目录不能部署，不能覆盖重试。
`private/` 下三份文件才是卡上私有材料；`public/` 只有 `public.bin` 与 `public.sha256`，兼容现有 `prepare_pairing.py`。
`identity.json` 只记公开状态及安全边界。复用原身份时核对公钥指纹，既有 `pairing.json` 无需更换。

准备输出是敏感备份；恢复其中初始随机状态会重新开始同一确定性序列，禁止重复部署、克隆或恢复旧状态继续使用。
故障恢复若保留身份，必须重新生成独立随机状态，而不是从备份恢复已用过的状态文件。

### 构建独立固件

```powershell
& ./.venv/Scripts/python.exe board/prj/build_software.py --xsa build/vivado/g4_usb_1/m01.xsa --output build/vitis/g6_sd_identity_1 --tool-root D:/AmdDesignTools/2026.1 --apps g6_usb --boot-images --g6-sd-identity
& ./.venv/Scripts/python.exe board/prj/verify_software.py build/vitis/g6_sd_identity_1
```

输出目录必须未存在；`--tool-root` 按实际工具安装位置调整。工具只构建，不生成私钥、不写卡、不接触板卡。不能与生产 provider 或旧 USB/JTAG 初始化开关混用。

### 写卡和用户验收

软件验证结果见本次实现记录。未生成真实材料、未写卡、未重启板卡之前，不把代码通过记为实板通过。
部署时先正常停止视频服务、完全断电，再将 SD 接到读卡器；重新核对卡身份、容量和文件系统，不盲用历史盘符。
备份旧 BOOT；仅在确认目标后将新 `BOOT.BIN` 与三份私有文件放入根目录，同步并读回核对，安全弹出后整读卡器拔插再复核。
本说明不提供会自动覆盖运行卡上随机状态的复制命令。
SD 卡需可写；如果写保护或无法可靠保存状态，应拒绝开始业务。
新固件和材料就绪后，日常 PC 命令为 `eyepqc run`，不带 `--dev-usb-bootstrap` 或 `--dev-identity-file`。
旧 USB 初始化固件继续沿用旧命令，不能仅删除参数就变成此模式。

用户验收至少包括：独立读卡器重插核对、真实 SD 冷启动、首次连接、停止重连、手动换钥、正常重启后连接，以及状态损坏/写入失败拒绝使用旧状态。
不会自动修改当前账号、TLS 证书、配对指纹或手机信任记录。
