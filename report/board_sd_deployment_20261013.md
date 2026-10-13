# Board SD 部署与 G0 冷启动记录（2026-10-13）

本报告仅负责板端。用户已报告 Android 可显示视频、约 40 fps 足够；本次没有重新测量手机帧率。
当前 SD 根目录镜像是独立 G0 DDR/定时器/LED 自检，不是 G6 视频应用；G6 自主密钥装载尚未闭环。

## 本轮新构建

旧 `g0_20261008b_startup_final2` 不在本地构建目录，未复用旧报告中的镜像。
执行 `board/prj/build_g0.ps1 -ToolRoot D:/AmdDesignTools/2026.1 -BuildName g0_board_sd_20261013_1`，
从当前目录源码重新生成 XC7Z020CLG400-2 XSA、匹配 BSP/FSBL、bitstream 和 G0 ELF/BOOT.BIN。

| 项目 | 本轮产物/证据 |
|---|---|
| XSA | `build/vivado/g0_board_sd_20261013_1/m01.xsa` |
| XSA SHA-256 | `0c5f1024abd509c7b2d59e115620c061ab9b77b9217f2a553e08710cbd217b2b` |
| BOOT.BIN | `build/vitis/g0_board_sd_20261013_1_startup/g0_startup/boot/BOOT.BIN` |
| BOOT SHA-256 | `3053401b6fca21b83092431656d3c0b0842b8d1cbcc77bbb54dc1c8eebd015da` |
| BOOT 字节数/build ID | 4,199,056 / `47f571a09684` |
| 清单 | `build/vitis/g0_board_sd_20261013_1_startup/g0_manifest.json` |
| 实现检查 | `build/g0_meta/g0_board_sd_20261013_1/implemented_io.txt.verified.txt`，H15/LVCMOS33/10 ns |
| 时序 | WNS 6.068 ns、WHS 0.130 ns；心跳 LED 外部输出无 output delay 的提示保留 |

G0 preflight 已通过；匹配 FSBL 的 `ps7_init.c/.h` 由构建工具与 XSA 逐字节比对，
Bootgen 生成并读回分区信息。`board_validated=false` 保留，不以构建替代实测。
DDR 自检只覆盖 64 KiB scratch，不能称全片 DDR 检查。

## 卡识别与文件级部署

用户连接读卡器后重新枚举：Disk 1 为 `DD-TEK READER`、USB、31,266,439,168 字节、MBR，
非系统/非启动磁盘；唯一分区对应 E: FAT32/Removable，卷序列号 `12345678`。
部署前重新校验这些条件，根目录完整列举只有 `System Volume Information`，原 `BOOT.BIN` 不存在。
因此没有被替换文件；未格式化、未擦盘、未改分区，也未覆盖其他根目录文件。

`board/output/sd_deploy_20261013_1/before.json` 保存识别、分区、目录及原 BOOT 缺失记录。
使用 `FileMode.CreateNew` 写 `E:/BOOT.BIN`，`Flush(true)` 后重新读取文件计算 SHA-256，
与本轮镜像逐字节摘要一致。部署结果保存在同目录 `deployment.json`。
如果后续部署时原 BOOT 已存在，必须先另存本机并校验后再替换；本轮“原文件不存在”的记录不能外推到其他卡。

读卡器出现前曾构建原生 xilffs/XSdPs 只读探针，ARM 编译和主机解析自检查通过。
探针未取得卡端有效结果，其 XSDB 客户端已停止；未调用写文件、格式化或删除接口。
读卡器路径已满足任务，因此不增加常驻工具；调查源码/ELF在忽略目录
`board/output/sd_read_probe_live_20261013_1/` 保留，不能宣称板上只读探测成功。

## 具体启动/供电依据

本地官方底板 V3.9 原理图第 2 页 BOOT OPTION 表和用户快速体验 V3.0 第 95 页近照均确认：
**红色二位 `BOOT_CFG` 的 1=OFF、2=OFF 为 SD Card**。它位于 BAT1 纽扣电池旁、PL_RESET 红按键旁；
按实物的 ON 标识判断方向，不能因图片旋转而猜上下。V3.9 正面装配图提供器件位置。

原理图第 6 页中 USB_UART 的 VUSB 单独经 U22 给 CH340 供电；VUSB 与 DC 输入降压后的 VBTN
都在 K1 主电源开关前，主 +5V 在 K1 后。因此只拔 DC 电源而保持 K1 接通，USB 仍可供主电源，不能当冷启动。
采集可保持 USB_UART 连接，关闭 K1 主开关并确认主 PWR/核心灯全灭，拔视频 USB Slave 和 JTAG，
断电插卡、BOOT_CFG 两位均 OFF，再打开 K1。上述为原理图连接证据，未用万用表实测断电电压；
若 K1 关闭后主灯仍亮，必须停止并核对剩余供电路径。

依据文件（本地官方资料，只读）：

- `D:/BaiduNetdiskDownload/正点原子领航者/3_开发板原理图和硬件相关文件/领航者ZYNQ底板原理图_V3.9.pdf`，SHA-256 `ec8b68eeb07e0743e6c60528444f6aeb457dc60e897ddf9eb86d5a56c1ab6a69`。
- `D:/BaiduNetdiskDownload/正点原子领航者/9_领航者ZYNQ底板V3.7版本（音频芯片为WM8960）/1_领航者ZYNQ开发板出厂综合测试/【正点原子】领航者ZYNQ开发板用户快速体验_V3.0.pdf`，第 9/95 页。
- `D:/BaiduNetdiskDownload/正点原子领航者/3_开发板原理图和硬件相关文件/硬件相关文件/领航者结构图&DXF&封装库/领航者底板/领航者ZYNQ底板结构图/领航者ZYNQ底板结构&装配图正面_V3.9.pdf`。

关键页已渲染核对，临时图在 `tmp/pdfs/sd-base-2.png`、`sd-base-6.png`、`sd-manual-95.png`、`sd-assembly-1.png`。

## UART/验收状态

本轮 Python 串口枚举为 COM4=CH340 调试 UART、COM7=USB 视频，端口号只适用于当前机器。
PC 8765 转发服务由 PC 聊天暂停。板端未自行管理 PC 进程。
2026-10-13 14:02:04（UTC+8）COM4 已被动打开，115200/8N1、DTR/RTS=false。
采集路径 `data/captures/g0/board_sd_cold_20261013_1.jsonl`，2400 秒超时、要求目标 uptime 至少 1800 秒、
UART 断线立即失败。完整验收要求匹配 build ID、BOOT_MODE=0x05、READY、连续 STAT、每分钟 DDR 复测，
且 ddr_err/assert/exception/timer_err=0，并由真实操作者确认 SD 卡、拨码、完全断电动作及 H15 LED 约 1 Hz 闪烁。

首次实际启动：2026-10-13 14:08:37（UTC+8）UART 确认 `Boot mode is SD`、`SD Init Done`、
`DMA Done`、`FPGA Done`，随后 `Handoff Address: 0x00000000` / `No Execution Address JTAG handoff`。
没有 G0 BOOT/READY，故本轮失败，不能算 30 分钟或冷启动通过。collector 已停止，原始 JSONL 保留，
SHA-256 `781c4914f31c7a2f824744903ca706d18f34ad071a7a2fbc9210757210bf138f`；下一轮使用新文件。

已确认的构建阻断：ARM GCC 生成的 `.note.gnu.build-id` orphan 被共用 `a9_ddr.ld` 放到地址 0，
ELF 多出 36 字节的 PT_LOAD；Bootgen 将其作为首个应用分区（load=0、exec=0x100000）。
匹配 FSBL 的 `image_mover.c` 对未签名/未加密的零加载地址在复制前退出循环，因此没有设定跳转入口。
不能据此宣称已复制覆盖 OCM 或损坏 FSBL。

协调聊天接管后，仅在共用 DDR linker 丢弃该构建标记段，并新增真实 ARM GCC 回归检查所有 LOAD 位于 DDR、
入口位于可执行 LOAD。所有共用该 linker 的 G0/G6/Keccak builder 都获得修复；已有历史镜像不被修改或重新验收。
新软件目录 `build/vitis/g0_board_sd_20261013_2_startup` 重新生成 BSP/FSBL，复用同轮已实现的 XSA/引脚/时钟证据，
没有重复综合未变的 RTL。应用仅剩一个 LOAD，Bootgen 应用 load/exec 均为 `0x00100000`；G0 preflight 通过。
新 BOOT.BIN 为 4,198,992 字节，SHA-256 `079482ff600bac35203dd75e72080940e8cc2bcd9a3d5d485dd51ffec584ec1c`。
build ID 仍为 `47f571a09684`（由应用 C/XSA 推导），必须结合 BOOT hash 和 source_inputs 区分镜像。
2026-10-13 19:02:16（UTC+8）用户接回卡后，重新核对同读卡器、磁盘/分区大小、FAT32 和卷序列号。
旧 BOOT 文件长度仍为 4,199,056，但 SHA-256 为 `a3c1c709b3690bcd792675f9a16b4b2e17ec483751da7987ef2b3d874292d03e`，
与首次写入时的摘要不同；逐字节比较有 67 字节变化，全部在 offset 0x60～0xbc，包括启动头 IHT/PHT 字段。
变化原因/发生时间未确定，不能凭此认定卡损坏或把全部现场异常归于 linker。
原文件已完整备份至 `board/output/sd_deploy_20261013_2/BOOT.before.bin` 并核对摘要后，才覆盖单个 `E:/BOOT.BIN`；
Flush(true) 后新文件读回摘要一致，其他文件未修改，未格式化/分区。
操作记录为同目录 `deployment.json`；因旧文件变化，增加安全弹出并重插读卡器后的持久性复核。
当前：新镜像写入及即时读回通过，重插后复核与冷启动/30 分钟/物理复位均未通过。
首次用户回复“已重插”后，Windows 读卡器 USB `VID_DD31&PID_3118/0123456789AB` 仍枚举但状态 Error、
ProblemCode=47，磁盘/卷未出现；这是安全移除状态，不能当持久性校验失败或宣称卡损坏。
已请用户重新插拔整个读卡器 USB 接口，暂不将卡放回板上；未禁用其他 USB 设备或重启电脑。

19:10（UTC+8）卡恢复为同一 31,266,439,168 字节磁盘/FAT32/卷序列号后，重插持久性检查**失败**。
卡上 BOOT.BIN 长度 4,198,992，重复读取 SHA-256 均为
`cd76192e42920e86e5d19372b2ce03793ace8d40afee31a4bc1a05b78b16309f`，不匹配新镜像。
再次有 67 字节变化，全部在 offset 0x60～0xbc，包括 IHT/PHT 偏移；变化字节包含 FAT 目录项样式的
UTF-16 字符和 `INDEXE~1`，但仅据此不能确定 SD 卡、读卡器、缓存或其他层的故障原因。
此轮重插未放回板卡，故不能将这次文件变化归因于板端 G0/FSBL。
原样副本保存于 `board/output/sd_deploy_20261013_2/BOOT.after_reinsert.bin`，摘要已核对。
不带 `/F` 或 `/R` 的只读 `chkdsk E:` 输出文件/目录检查未发现问题（同时有 Access is denied 提示）；
这不证明介质和读卡器可靠，不以此跳过持久性失败。
该阶段暂停 SD 上板，不再反复覆盖原卡；随后改用用户提供的另一空卡（见下节）。
不写 BOOT_MODE 寄存器，不以 JTAG 暖启动作为 SD 证据。

复位采集器原先在第二次 BOOT 后立即停止，漏第二次 READY/STAT，已改为第二次 STAT 后停止。
`board/prj/tests/test_g0_capture.py` 用模拟 UART 复现并验证完整第二次启动证据；该 1 项测试和原 7 项日志解析测试通过。

## 新卡重建与真实 SD 启动

用户另提供一张卡，同读卡器容量仍为 31,266,439,168 字节，但最初为 GPT/两个 Windows 不可读分区。
用户先自行格式化为 FAT32，GPT 分区表未改变；匹配 BSP 的 `FF_LBA64=0` 不启用 GPT 路径，因此未直接写入。
用户明确授权“那你重建把”，重建前复核 Disk 1 非系统/启动盘、USB 读卡器序列号、GPT GUID
`e15a0b60-a013-8a4c-86a9-af49524c4746`、单个 20 GiB 分区及卷序列号 `2CC7F6B3`，
根目录只有 System Volume Information。管理员脚本仅清除这张新卡，原卡与电脑 NVMe 盘未改动。

初次 Clear-Disk 后 Windows 仍呈空 GPT，Initialize-Disk 报已初始化；保留日志后用 Set-Disk 转换 MBR。
旧 E: 访问路径仍被系统保留，New-Partition 指定 E 失败；再次核对为空 MBR 后改用空闲 F:，未重复清除。
19:26:07（UTC+8）完成新分区/FAT32 和 BOOT 写入；MBR signature=3282445593，分区 offset=1048576、
size=31265390592、type=0x0c，F: 卷序列号 `9AA2764D`。镜像长度/摘要与第二次构建一致。
用户安全弹出并拔插整个读卡器后重新核对磁盘 signature/卷身份，BOOT 摘要仍一致，**新卡持久性复核通过**。
这证明本轮新卡路径成功，不证明原卡问题根因或长期可靠性。
重建失败过程/成功元数据分别保留在 `board/output/sd_new_card_20261013_1/`、
`sd_new_card_20261013_1_resume/` 和 `sd_new_card_20261013_1_resume2/`。

用户确认准备好新卡、BOOT_CFG 两位 OFF、K1 完全断电、核心板灯灭且仅保留 COM4，采集就绪后确认上电。
19:29:41.87（UTC+8）日志捕获 `SUCCESSFUL_HANDOFF`、G0 BOOT build=`47f571a09684` / boot_mode=`0x05`、
DDR PASS、TIMER PASS 和 READY；随后连续 STAT 的故障计数为零，用户另确认“LED正常闪烁”。
采集 session=93273，日志 `data/captures/g0/new_sd_cold_20261013_1.jsonl`，只读 COM4，不访问 JTAG、不写 UART。
**SD 独立进入 G0 已实测；本轮十分钟例外通过，物理复位仍待验收。**

用户随后要求“10分钟就行”，本轮目标改为 uptime >=600 秒的用户例外，不宣称原 1800 秒/30 分钟已测。
collector 的 CLI 原为 minimum_seconds=1800；自动回查在最新 640 秒样本后只对主机 collector 发 Ctrl-C，
退出码 1/KeyboardInterrupt 是用户要求提前结束采集，不是板卡错误。未停止/复位板卡，COM4 已释放。
原始 UART 日志保持不变，SHA-256 `ace037eb435f56b9e5bb90c462abb29187841285349ac40ce632f5f1be4d9d3b`。
复制为 `new_sd_cold_20261013_1.10m_evidence.jsonl` 后，附真实用户确认的来源和有意停采说明；
衍生文件 SHA-256 `fc6a2370b7c7674266999c8e6874835339f716deb06a802d63625d25a916108c`。
以既有 `verify --scenario sd_cold_start_30m --minimum-seconds 600` 离线复核通过，
legacy scenario 名称不表示三十分钟已测；独立结果 `data/captures/g0/new_sd_cold_20261013_1.10m.result.json` 明确 scope。

| 十分钟用户例外结果 | 实测 |
|---|---|
| 时间窗（UTC+8） | 19:29:41.871151 至 19:40:21.944488 |
| uptime / STAT / ticks | 640 秒 / 64 条 / 12800 |
| BOOT / mode / DDR PASS | 1 次 / 0x05 / 12 次 |
| ddr_err / assert / exception / timer_err | 全为 0 |
| UART 断线 | 0 |
| 人工观察 | 用户确认 SD/拨码/断电准备及上电，另答“LED正常闪烁”；非电压/频率仪测 |

原三十分钟没有执行；完整 G0 仍缺物理复位，新卡一次成功也不等于全介质寿命检查。
临时自动回查已在下一步需要人工动作时暂停；本轮 9 项 G0/collector/DDR-linker 定向测试通过。
本轮只做 G0 自检，不装载业务私钥/seed，也不能替代 G6 视频自主启动。

复位入口已用官方资料核对并渲染检查：核心板装配图第 1 页 KEY1 / `PS_RST` 位于 U1 大芯片右侧、
U7 下方、U2 上方；核心原理图第 4 页 POWER ON RESET 中 KEY1 经 HX811T #MR/#RESET 驱动 PS_POR_B。
这是 PS POR 按键，不是底板 PL_RESET、PS_KEY0/1，也不是同页仅上拉的 PS_SRST_B。
原理图 SHA-256 `1c8cf8105e91d762d29ad604e82b629b3921fa474d5a0311ed6c04237db107ea`，
装配图 SHA-256 `7b5cfc3ae3b82d418bfaea0936ddccd81ab1bf4a9da3f4a5aa10282bea0a3686`。
下一轮另开被动 `reset_probe`，先捕获新 SD baseline BOOT/READY，再提示用户按该 PS_RST 恰好一次，
保留第二 BOOT/READY/STAT 后才验收，不写软件 BOOT_MODE 或模拟按键。

## G6 独立视频限制

现有 `g6_mobile_bridge_20261012_1` 的固件清单 73 项哈希核对通过，
但 `verify_software.py` 全构建追溯检查失败：`software_build.json` 引用缺失的
`g6_usb/external_sources/src/xusbps_endpoint.c`。没有修改摘要或跳过检查冒充全检通过。

G6 启动仍等待 `g6_ready=PROVISION_MAGIC`，从 JTAG mailbox 读静态 ML-KEM 私钥与 seed。
直接创建 G6 BOOT.BIN 仍不能自主认证视频；可选的开发态 SD 私钥/每次启动新熵装载需要另行设计和授权，
并明确明文 SD 私钥、可信 PC、JTAG 及非生产安全边界。生产 provider、真实熵源/secure boot/eFuse 不由本次 G0 验收完成。

本轮未写真实私钥到提交固件或 SD、未烧 eFuse、未做全 DDR 检查或手机新实测。
