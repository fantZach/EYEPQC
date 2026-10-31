# CF7020B 板端部署教程（开发候选，用户验收）

本教程针对领航者 CF7020B / XC7Z020、OV5640 接 P2、USB0 Slave/P4 的现有工程。
板端仅 Vitis Standalone，不刷 Linux、不写 QSPI/eFuse，不启用 PS 网口。
验收统一由用户完成；离线构建/打包不会自动将 `board_validated` 或任何 G 门禁改成通过。

## 1. 交付与前提

- 本地候选 ZIP 包含 `BOOT.BIN`、脱敏 `manifest.json`、本教程、第三方许可和 `SHA256SUMS.txt`。
  **仅本机开发使用**；AMD/生成物及链接依赖的外部分发审查未闭环，暂不作为 GitHub 二进制附件。
- 最新 `_6` 固件仅完成离线验证。此前首次 USB QUERY 超时、第二次成功的问题仍需实板确认；不要据此教程称问题已解决。
- Windows 需要视频 USB CDC 驱动、CH340 调试串口驱动、匹配 PC CLI、已准备好的 WSS/账号材料，以及受保护的板端测试身份文件。
- 构建需要 Python 3.12+、根目录依赖、原生 GCC、Vivado/Vitis 2026.1 和 Zynq-7000 器件包。
- 不把真实私钥、seed、账号或用户视频放入源码/BOOT/SD/候选包。PC 明文 USB 注入开发材料，PC 因而属于可信边界，不是生产安全。

仓库协议、安全边界和 PC 完整部署入口：
[USB 初始化契约](https://github.com/fantZach/EYEPQC/blob/main/doc/g6_sd_usb_bootstrap.md)、
[PC 说明](https://github.com/fantZach/EYEPQC/blob/main/pc/README.md)。
本包不附身份，也不生成/覆盖操作者现有身份。

### 1.1 全新部署：显式创建专用开发身份（已有身份跳过）

已信任且正在使用的板端测试身份必须复用，不因升级运行本节；不要重建身份来绕过手机已保存的 pin。
只有全新环境还没有身份时，操作者在可信 Windows PC 的源码环境离线执行下面命令。
先安装根目录及 `pc/requirements.txt` 依赖（已有 `.venv` 时复用，不重建）：

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt -r pc/requirements.txt
$IdentityParent = "$env:LOCALAPPDATA/EYEPQC/development-identities"
if (-not (Test-Path -LiteralPath $IdentityParent)) { New-Item -ItemType Directory -Path $IdentityParent -ErrorAction Stop | Out-Null }
$Identity = Join-Path $IdentityParent 'board-identity-new-1'  # 必须是未存在的新绝对目录
& ./.venv/Scripts/python.exe board/prj/prepare_dev_identity.py --output $Identity
```

必须退出 0 并输出 `DEVELOPMENT_IDENTITY_CREATED`。工具只接受新的绝对本机目录，拒绝 UNC/链接/覆盖；
先保护 `private/` 为当前用户/SYSTEM 独占，再检查新文件 ACL，之后才取 OS 随机 64 字节并执行已固定依赖
`kyber-py` 的 ML-KEM-512 `key_derive`，不提供固定 seed 参数。生成后验证长度、内嵌公钥、FIPS203 `H(ek)` 和私钥读回。

| 新目录内容 | 用途 |
|---|---|
| `private/board-test-identity.bin` | 精确 1632 字节私钥；仅可信 PC 持有，不发给手机/服务器/SD，不进入候选包 |
| `public/public.bin` | 精确 800 字节公钥，交给 PC 的公开配对生成流程 |
| `public/public.sha256` | 该公钥的 SHA256 指纹；通过独立可信渠道核对 |
| `identity.json` | 开发态/PC 可信/用户验收待定等公开元数据，不含私钥或生成输入 |

`public/` 只有两份公开文件。日志只打印状态与公开指纹，不输出私钥/seed。
不会保存独立 keygen seed 文件；私钥本身仍含算法要求的秘密字段，必须受保护。
这是开发参考 Python KEM，不是生产密码模块：仅尽力覆盖自有可变缓冲，Python/库/OS 中的不可变及原生副本无法保证物理清零。
这次身份生成的 64 字节输入不是冷启动时的 32 字节 seed；后者仍由 PC 每次实际 USB 初始化重新随机生成，不能复用。
失败可能留下本次新建的空目录、零字节文件或不完整私有材料；未输出成功时不部署，保留现场核对，不覆盖重试。

先按 PC 教程完成 `eyepqc init`、证书和账号准备。全新且没有旧配对时，用同一身份的 `public/` 生成 schema2：

```powershell
& ./.venv/Scripts/python.exe pc/src/host/prepare_pairing.py --identity-dir "$Identity/public" --endpoint wss://124.70.38.245:8765/stream --config-file "$env:LOCALAPPDATA/EYEPQC/pc/data/public/pairing.json"
$BoardIdentityFile = Join-Path $Identity 'private/board-test-identity.bin'
```

公网地址仅为当前实例示例，须与实际 TLS SAN/手机地址一致；局域网替换为对应可信 WSS 地址。
`--config-file` 不带 `--token-file` 才是账号 schema2；不要使用旧版 `--output-dir` token 演示路线。
该命令拒绝覆盖已有配对；已有身份/配对的部署不运行它。私钥可保留在这个受保护目录，后续显式传 `$BoardIdentityFile`；
若另外迁到 PC 的 private 目录，必须先确认目标 ACL，排他新建并读回核对，不覆盖现有身份。

## 2. 构建与生成本地候选

已有经确认匹配的完整视频 XSA 时，可直接进入软件构建。XSA 必须包含相机/DMA/AES-GCM、USB0 与 SD0，
不能拿纯 M01 心跳或其他板卡 XSA 替代，也不能混用不同工程的 FSBL/bit。
若从源码重建硬件，从仓库根执行，示例目录必须未存在：

```powershell
& 'D:/AmdDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source board/prj/build_g3.tcl -tclargs build/vivado/g6_user_hw
# 检查 Vivado 退出码、DRC/时序报告及生成的 m01.xsa；失败时停止，不继续软件构建。
& ./.venv/Scripts/python.exe board/prj/build_software.py --xsa build/vivado/g6_user_hw/m01.xsa --output build/vitis/g6_user_sd --tool-root D:/AmdDesignTools/2026.1 --apps g6_usb --g6-dev-usb-bootstrap --boot-images
& ./.venv/Scripts/python.exe board/prj/verify_software.py build/vitis/g6_user_sd
```

必须看到 `SOFTWARE_VERIFY_OK`，且软件报告为 `status=PASS`、BSP/ARM 应用及 FSBL 通过。
`board_accessed=false` / `board_validated=false` 是正确的未上板状态，不手工改清单。
打包时重新核对当前源码、XSA、最终生成代码和 BSP，不接受只保留一份旧 PASS 报告：

```powershell
New-Item -ItemType Directory -Path build/local_board_delivery -ErrorAction Stop
& ./.venv/Scripts/python.exe board/prj/package_candidate.py --workspace build/vitis/g6_user_sd --output build/local_board_delivery/EYEPQC-Board-development-candidate.zip
Get-FileHash build/local_board_delivery/EYEPQC-Board-development-candidate.zip -Algorithm SHA256
```

如果已有输出目录，只省略 `New-Item`；ZIP 文件本身必须不存在。工具拒绝覆盖、链接路径、错误 profile 和过期哈希，
只导出固定文件，不递归打包工作区。`manifest.json` 不复制包含本机绝对路径的原始构建清单；
始终记录 `development_only=true`、`user_acceptance=pending`、`local_use_only=true`。
工具不接板卡、不打开 COM/JTAG、不写 SD、不上传。请另外保存 ZIP SHA256，供验收时固定候选版本。

## 3. 写 SD 前确认（用户执行）

1. 手机停止观看；PC relay 正常 Ctrl+C 退出。确认视频 COM 无其他进程占用，不强杀无关程序。
2. 关闭 K1；确认核心板灯完全熄灭。USB/JTAG/调试串口可能反向供电，若仍亮灯，必须断开相关供电线，不能将其计为冷启动。
3. 取出 SD 接电脑读卡器。只做普通 FAT32 启动文件更新；本教程不提供格式化、分区或原始磁盘写入命令。
4. 先通过 Windows 磁盘管理或下面的只读命令，核对盘符、读卡器型号、容量、分区和文件系统。`S:` 只是示例，绝不能照抄猜测。

```powershell
Get-Volume
Get-Partition -DriveLetter S | Get-Disk | Format-List Number,FriendlyName,Size,PartitionStyle
Get-Volume -DriveLetter S | Format-List DriveLetter,FileSystemLabel,FileSystem,Size
```

已有卡若不可读、容量为 0、文件异常，不写卡、不自动修复/格式化；先排查卡/读卡器。
解压候选包到电脑的独立新目录，检查 `manifest.json` 与 `SHA256SUMS.txt`，并重新计算 `BOOT.BIN` SHA256。

## 4. 保留旧镜像、写入与持久性检查（用户执行）

先在电脑建立新的备份目录，将 SD 上旧 `BOOT.BIN` 复制过去并分别计算源/备份 SHA256，确保一致；
不要覆盖以前备份。另记录候选 ZIP hash、旧 BOOT hash、新 BOOT hash、实际 SD 型号/容量和盘符。

下面脚本只适用于**已经人工核实**的 SD 盘符。先修改 `$sdRoot`、`$candidate` 到实际目标。
默认示例路径是占位，不会替你选择磁盘。新文件用 CreateNew/WriteThrough、Flush(true)，先读回再重命名；
旧 BOOT 保留在 SD，不删除。执行期间不要拔读卡器。

```powershell
$ErrorActionPreference = 'Stop'
$sdRoot = 'S:\'  # 必须先核对并修改；不是系统盘、仓库或其他移动硬盘
$candidate = 'C:\board-candidate\BOOT.BIN'  # 解压候选中的文件
$expected = (Get-Content 'C:\board-candidate\manifest.json' -Raw | ConvertFrom-Json).boot_sha256
$sourceHash = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash
if ($sourceHash -ine $expected) { throw '候选 BOOT 与清单不一致' }
$newFile = Join-Path $sdRoot 'BOOT.NEW'
$activeFile = Join-Path $sdRoot 'BOOT.BIN'
$oldFile = Join-Path $sdRoot ('BOOT.PREV.' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.BAK')
if ((Test-Path -LiteralPath $newFile) -or (Test-Path -LiteralPath $oldFile)) { throw '目标暂存/备份已存在，停止核对' }
$source = [IO.File]::OpenRead($candidate)
$dest = $null
try {
    $dest = [IO.FileStream]::new($newFile, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None, 65536, [IO.FileOptions]::WriteThrough)
    $source.CopyTo($dest)
    $dest.Flush($true)
} finally {
    if ($dest) { $dest.Dispose() }
    $source.Dispose()
}
if ((Get-FileHash -LiteralPath $newFile -Algorithm SHA256).Hash -ine $expected) { throw '写入读回失败，保留现场' }
if (Test-Path -LiteralPath $activeFile) { Move-Item -LiteralPath $activeFile -Destination $oldFile -ErrorAction Stop }
Move-Item -LiteralPath $newFile -Destination $activeFile -ErrorAction Stop
if ((Get-FileHash -LiteralPath $activeFile -Algorithm SHA256).Hash -ine $expected) { throw '最终读回失败，保留现场' }
```

Windows 安全弹出 SD，然后将**整个读卡器 USB 插头**拔下再接回，SD 留在读卡器内。
重新确认同一张卡/盘符，再计算 `BOOT.BIN` hash，须与新候选一致，旧备份也应保持原 hash。
写入后立即读回不等于独立拔插持久性。失败时停止，保留现场，不反复覆盖或擅自格式化。

## 5. 无 JTAG 冷启动与初始化（用户执行）

1. 安全弹出，K1 断电且核心灯全灭后将卡插回板卡。
2. CF7020B `BOOT_CFG` 两位按 SD 启动标记设为 OFF（远离 ON）；若板卡丝印/硬件版本不同，先核对官方资料，不猜拨码。
3. 拔掉 JTAG，暂不接视频 USB；只保留不会反向供电的调试串口。
4. 新终端先采集调试串口，再打开 K1。调试串口示例 COM4，115200/8N1，DTR/RTS 关闭：

```powershell
& ./board/prj/capture_uart.ps1 -Port COM4 -Seconds 600 -Output data/captures/g6_user_cold_unique.log
```

该工具只读 UART；日志名必须未存在。记录 FSBL SD 启动/handoff、`G6_DEV_USB_WAIT boot_mode=0x05`，
以及 LED/接线/断电情况。不要仅凭 LED 或 UART 的一次 READY 判整个链路通过。
5. 接视频 USB Slave。Windows 列出视频 CDC 端口（历史 COM7），它不是 CH340 的调试 COM4；
   实际编号以设备管理器为准，每次更换 USB 口都应核对，不硬编码照搬。
6. PC 已按教程配置账号、TLS、SSH 和 schema2 公钥 pin；提供匹配的受保护测试身份，运行：

```powershell
eyepqc config set serial_port COM7
eyepqc check
eyepqc run --dev-usb-bootstrap --dev-identity-file $BoardIdentityFile
```

私钥为 1632 字节 ML-KEM-512 开发身份，文件与父目录只允许当前用户/SYSTEM；不得放在 SD 或发给手机。
`$BoardIdentityFile` 为第 1.1 节创建的私钥路径；新终端应重新设置该变量到真实受保护文件，已有部署则使用原身份路径。
普通 `eyepqc run` 不注入开发身份。USB 查询 WAIT 后才允许本次一次性装载，成功时 PC 报 `DEV_USB_READY`，
板端 UART 报 READY；新随机 seed 由 PC OS 在实际初始化时生成，不由操作者固定填写。
7. Android 使用匹配可信 WSS 地址和账号登录，自动取得公开配对；确认真实视频、认证帧增长、停止/重连与换钥。
   若用户约 40–45 fps 已够用，不为凑更高数字改认证或丢掉错误统计。

## 6. 错误处理与回滚

| 现象 | 操作 |
|---|---|
| DAP/JTAG 错误 | SD 验收不依赖 JTAG，不插回 JTAG 暖启动掩盖冷启动失败；保存 UART 与接线记录 |
| 无视频 COM/只有调试串口 | 核对供电、Slave 模式、P4 线与驱动；不要抢占 COM4 当作视频端口 |
| 首次 QUERY 超时、第二次成功 | 保留每次 PC/UART 时间、state/epoch/TX/clear_halt 公开计数；真实问题仍待验证，不将第二次成功记为首连通过 |
| `FAULT`、乱序、半包、身份 pin 不匹配 | 停止并保留脱敏日志；不重复 DATA、不改 pin 绕过认证，不用 JTAG“恢复通过” |
| TLS/登录失败 | 按 PC/Android 教程核验证书地址/时间、账号和已有 pin；不关闭校验或使用明文登录 |
| 无 FSBL/SD 迹象 | 核对 SD 持久性、FAT32/启动拨码和版本；不格式化原卡、不混拼 FSBL/bit |

需回滚时：手机停止、PC 正常退出、K1 完全断电后取卡；核对同一张卡并保存失败 BOOT/hash/日志。
确认电脑或 SD 上旧备份 hash 正确，沿第 4 节相同的排他新建/读回/提升流程恢复旧 BOOT，失败候选保留另名。
独立读卡器拔插后再复核。不要直接覆盖唯一旧备份；恢复后按旧版本对应的身份/配置重新验证。

## 7. 用户统一验收记录

每轮固定 ZIP 与 BOOT hash；保留以下记录，未做填“未测”，失败填实际失败，不修改原始日志：

| 项目 | 用户填写 |
|---|---|
| 日期、板卡型号、PC/Android 版本、ZIP/BOOT hash | |
| SD 型号/容量/文件系统；备份及拔插后 hash | |
| 核心灯全灭、JTAG 断开、SD 启动拨码、摄像头/USB 接线 | |
| UART 文件、FSBL/boot_mode、WAIT/READY、错误状态 | |
| 第一次连接结果、后续逐次重连结果；不是只记最后一次 | |
| 认证帧起止、真实时长、显示 fps、丢片/丢帧/错误与队列统计 | |
| 手动换钥、30 分钟自动换钥、同账号显式接管 | |
| STOP、重连、重新冷启动；故障测试分别记录 | |
| 原始日志位置、验收结论与不接受项 | |

本教程不规定用户必须接受某个时长，也不将历史时长例外改成满两小时结果。
你的结论用于后续正式候选冻结；未验证的生产熵源、身份存储、安全启动和完整故障门禁继续单列。
