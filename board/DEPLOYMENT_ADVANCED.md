# 开发板进阶部署与构建

普通安装按 [新手教程](DEPLOYMENT.md)。当前路线是 SD 本地身份，不是历史 USB 注入身份固件。
用户已确认连接可用及首次连接问题修复；本文提供构建/配置步骤，不新增实测或关闭其他门禁。

## 1. 构建环境

CF7020B / XC7Z020、OV5640 接 P2，Vitis Standalone，USB Slave/P4；不依赖 PS 网口或 Linux。
需要 Python 3.12+、根目录与 PC 依赖、原生 GCC、Vivado/Vitis 2026.1 和 Zynq-7000 器件包。
XSA 必须包含匹配的摄像头、DMA、AES-GCM、USB0 和 SD0；不能混用别的工程的 FSBL/bitstream。

在仓库根目录执行，按本机安装修改工具路径，输出目录必须未存在：

```powershell
& 'D:/AMD/2026.1/Vivado/bin/vivado.bat' -mode batch -source board/prj/build_g3.tcl -tclargs build/vivado/sd_hw_new
& ./.venv/Scripts/python.exe board/prj/build_software.py --xsa build/vivado/sd_hw_new/m01.xsa --output build/vitis/sd_new --tool-root D:/AMD/2026.1 --apps g6_usb --boot-images --g6-sd-identity
& ./.venv/Scripts/python.exe board/prj/verify_software.py build/vitis/sd_new
```

每步检查退出码。硬件需通过 DRC/时序，软件必须输出 `SOFTWARE_VERIFY_OK`。
离线报告 `board_validated=false` 正确，不手工将其改为实板通过。已有匹配 XSA 可跳过硬件重建。

## 2. 准备身份及独立随机状态

此步骤只供首次配置或受控故障恢复；日常升级不运行。已有身份继续复用，避免无故改变手机指纹。
可信配置电脑可能保留秘密，不宣称能抵御该配置者；运行卡禁止恢复已用过的随机状态。
父目录先准备好，目标目录必须是不存在的本机绝对目录，工具拒绝覆盖或链接路径。

```powershell
$Prepared = Join-Path $env:LOCALAPPDATA 'EYEPQC/sd-new-1'
$Existing = Join-Path $env:LOCALAPPDATA 'EYEPQC/pc/data/private/board-test-identity.bin'
& ./.venv/Scripts/python.exe board/prj/prepare_sd_identity.py --output "$Prepared" --identity-file "$Existing"
```

仅全新环境没有旧身份时省略 `--identity-file`，这会生成新身份，必须重新完成可信配对。
必须输出 `SD_IDENTITY_PREPARED` 且退出 0；失败保留现场，不部署部分文件或覆盖重试。
`private/` 中 `EYEKEY.BIN`、`EYERNG0.BIN`、`EYERNG1.BIN` 交给 SD，不进入 BOOT、Git、日志、手机或服务器。
`public/` 只有公钥及 SHA256；已有配对应核对它与当前身份完全一致。

全新且没有旧配对时，用同一身份公开文件创建 schema2，示例地址必须改为实际值：

```powershell
& ./.venv/Scripts/python.exe pc/src/host/prepare_pairing.py --identity-dir "$Prepared/public" --endpoint wss://203.0.113.10:8765/stream --config-file "$env:LOCALAPPDATA/EYEPQC/pc/data/public/pairing.json"
```

命令拒绝覆盖。身份不变时不要重建配对；不得为了绕过手机指纹错误生成新身份。

## 3. 生成本机程序包

```powershell
New-Item -ItemType Directory -Path build/local_board_new -ErrorAction Stop
& ./.venv/Scripts/python.exe board/prj/package_candidate.py --workspace build/vitis/sd_new --output build/local_board_new/board.zip
```

打包会重新校验来源，只导出 BOOT、公开教程、许可和脱敏清单，不收集身份或状态文件。
AMD/生成物外部分发审查未闭环，板端包仅本机使用，不能直接上传作公开固件。

## 4. 写卡、启动与观测

写卡前正常停止手机与 PC 服务，完全断电且核心灯全灭后取卡，重新核对卡的盘符、容量及 FAT32。
先备份旧 BOOT，首次材料只写到确认没有身份/状态文件的新目标；已有运行卡升级仅改 BOOT，保留状态。
写入后读回，安全弹出并整体拔插读卡器后再核对。失败不反复覆盖、格式化或恢复旧随机状态。
具体接线、BOOT_CFG 双 OFF、启动和 PC `eyepqc run` 见新手教程。

调试串口可按实际端口只读采集，输出日志名必须未存在：

```powershell
& ./board/prj/capture_uart.ps1 -Port COM4 -Seconds 600 -Output data/captures/sd_cold_new.log
```

`G6_SD_IDENTITY_READY experimental=1` 说明启动就绪；手机实际认证帧、STOP/重连/换钥及故障另行验收。
日志只保留脱敏状态，不发送身份、随机状态或账号材料。首次连接已由用户反馈修复，本次没有新增量化测试。

## 5. 历史兼容与边界

旧 JTAG、USB 初始化配置仅用于明确选择的历史调试镜像，使用方法见 [旧 USB 契约](../doc/g6_sd_usb_bootstrap.md)。
旧模式不能通过删除 PC 参数变成本模式，本模式也不在故障后退回 PC 注入秘密。
SD 任一槽损坏或提交失败则关闭会话，不回退旧槽；故障恢复保留身份时重新生成独立随机状态。
没有硬件熵、受保护存储或整卡回滚保护，SD 内部任意断电持久性不能由同步/读回保证。
详见 [SD 文件与状态契约](../doc/g6_sd_identity.md)、[账号握手](../doc/account_ephemeral_protocol.md)、[验收表](../doc/deployment/ACCEPTANCE.md)。
