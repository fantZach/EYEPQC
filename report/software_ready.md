# 软件阶段交付记录

更新：2026-10-07。本记录覆盖电脑端软件和首次 G3 失败诊断，不替代整机门禁。

## 软件同步复核（2026-10-07）

最新完整 `run_demo.ps1 -Mode Check` 为 18/18 PASS，包含新 USB 恢复 helper 检查，
M04/M05 使用原生 XSim。当前默认 `usbfix3_20261007` 的启动/BSP/哈希预检和
Windows PowerShell 5.1 的 G7 `-CheckOnly` 通过。本次同步未访问板卡。
可上传的结构化证据、实施文件 Git blob 身份及前轮自动板测摘要见
[软件同步验证汇总](software_sync_20261007.json)。构建镜像、密钥、原始采集与日志保留本机；
不将代码推送解释为二进制附件交付或 G7 物理拔插通过。

后续演示窗口、换钥/篡改按钮、连续认证 JPEG 录制和时间戳回放的电脑端实现已完成；
相关 G6 9/9、演示 5/5 及实际 Tk 检查通过，见 [演示完成记录](demo_software_ready.md)。
新界面的实机行为和录像吞吐仍待验收；默认完整回归新增为 19 个入口，最新完整运行仍是上述 18/18。

## 2026-10-07：G3 固件就绪超时修正

用户执行 `run_demo.ps1 -Mode G3`，哈希/BSP 查询通过，随后出现
`G3_BOOT_OK` 和 `G3 boot timeout`，未进入采集或加密。
原始日志在 `data/captures/g3_20261007_103831_618556/frame_000/xsdb.log`。
第一次当前 JTAG 状态读取：CPU0 PC=`0x00103aac`，对应
`Xil_UndefinedExceptionHandler`；邮箱前 64 字节均为零。
后续读取时板端状态已变化为 ROM 地址及 AHB transaction error，不能据此推断新镜像运行结果。

旧四个应用和 FSBL 的链接 map 都包含工具链通用 `crt0.o`，而没有链接 BSP 的
`xil-crt0.o`。这是确定的构建缺陷：通用启动代码重设栈布局，并跳过 BSP 全局定时器启动。
此前哈希、驱动查询及协议回归未覆盖该启动路径，因此不能凭它们宣告固件启动正常。
此次采用安装内 AMD `scripts/specs/arm/Xilinx.spec` 链接；预检新增启动成员检查，
已实际验证旧 5 份 map 全部被拒绝、新 5 份全部通过。

新目录 `build/vitis/software_ready_20261007` 保留同 XSA/bitstream/PS 初始化，
重建四份 ELF、匹配 FSBL 和四份 BOOT.BIN；旧目录不覆盖。
预检通过 98 项应用输入/产物哈希、715 项生成输入和真实 BSP 查询。
G3 ELF 反汇编确认 `_start` 调用 `__cpu_init`、`XTime_SetTime` 后再进入 `main`。
G3 主机边界/篡改检查与 G6 三项离线集成检查通过。
G3 Tcl 的就绪/超时两条路径已用全替换硬件命令的 mock 验证，日志见
`build/g3_tcl_checks/`；本机 xsdb.bat 在 Tcl 报错时仍可能返回 0，主机继续严格要求
`G3_JOB_DONE` 标记，不能仅凭进程退出码判定通过。Python 和 PowerShell 语法检查通过。

统一入口默认使用新目录；XSDB 输出改为 `G3_LOAD_OK`（下载命令完成）和
`G3_READY_OK`（固件邮箱就绪），超时时记录 CPU 状态与邮箱前 64 字节。
本次诊断仅连接现有 hw_server 读取状态；没有重新下载镜像、下发采集任务或写启动介质。
**新镜像仍为 `board_validated=false`，需要用户重新上电后执行 `run_demo.ps1 -Mode G3`。**
启动缺陷已离线修正，但本次板端超时是否消除仍须实机证明。

用户随后复测，软件预检仍通过，但 XSDB 在首次选择 APU 时失败，只枚举到
`DAP (AHB AP transaction error, DAP status 0x30000021)` 和 `xc7z020`。
日志：`data/captures/g3_20261007_104720_535028/frame_000/xsdb.log`。
此轮尚未执行系统复位、PS 初始化、bitstream/ELF 下载，不能用于判断新固件启动是否修复。
新增 `run_demo.ps1 -Mode JtagCheck`，只连接/枚举/选择调试目标，不复位或访问板端内存。
本次只读复查结果一致，日志在 `build/jtag_checks/20261007_104832_070968/targets.log`。
现停在用户完整断电、启动模式核对及硬件服务重连步骤，具体命令见 bringup 指南。

## 本轮修正

- 修正 G3 的 DMA 配置查询：经典 BSP 使用 `XAxiDma_LookupConfigBaseAddr`，SDT 使用基地址查询。
  UART 同样区分经典设备 ID 与 SDT 基地址；真实生成的 AMD 配置表在 PC 上验证 UART、两路 DMA 和 USB 查询。
- 经典 BSP 使用 `xtime_l.h`，SDT 保留 `xiltimer.h`；USB 中断分别使用经典 GIC 配置或 SDT 原生封装。
- USB 库构建只保留使用的探针缓冲和函数，使 G3/G4/G5/G6 均可在 `-O3 -Wall -Wextra -Werror` 下编译。
- 用 `prj/build_software.py` 与 `prj/generate_bsp.tcl` 固化 HSI/BSP/ARM GCC 构建过程，解决此前仅有手工构建记录的问题。
- G6 启动前核对应用清单；`--verify-only` 只检查文件，不读开发私钥，不接触板卡。
- G4/G5/G6 帧率计时改用高精度 `perf_counter`，修复多帧落在同一 `monotonic` 计时刻度时除零的问题。
- 增加根目录 `run_demo.ps1`，统一电脑检查、构建、开发素材准备、预检和用户实机入口。

## 构建与验证

2026-10-06 历史产物：`build/vitis/software_ready/`（启动链接缺陷，已停用）。同一 XSA 下四个 ARM ELF、匹配 FSBL、四份 `BOOT.BIN`
均已生成。BSP 编译 129 个源文件；FSBL 的 PS 初始化与 XSA 完全一致，ELF 的加载段位于 OCM；
Bootgen 已回读镜像，确认 FSBL→bitstream→应用的分区组成。所有启动介质仍未写入。

`software_verification.json` 记录四个应用共 90 项源文件/XSA/二进制哈希检查，另核对 710 项
生成 BSP、FSBL 和编译命令输入；真实 AMD 配置表查询通过。四个应用均保持 `board_validated=false`。
供应商 FSBL 生成日志保留 `Hsi 61-10` MSS 兼容提示；当前没有开启 RSA Secure Boot。

完整电脑回归由 `prj/check_software.py` 执行，包含依赖固定版本、向量一致性及 M00、AES MVP、
M01～M05、M07～M10、M12、G3、G5、G6 共 17 个检查入口。
日志与机器可读结果见 `build/software_checks/final_goal/`。
最终结果为 **17/17 PASS**，累计检查耗时约 223 秒；所有检查均为电脑端范围。
原先受工具环境影响的 M04/M05 原生 XSim 本轮已通过；默认 GCC 本轮可以正常启动，
没有替换 XPM 模型、忽略断言或放宽用例。

G6 新增 3 项内存 USB 集成测试：真实 C ML-KEM/会话代码与 Python 主机互通；
20 次新鲜握手/换钥、软件 JPEG 分片认证、密钥清零、坏 Finished、坏 Tag 和重放拒绝。
JPEG 是合成图片，GCM 是软件参考，USB 是内存分片流，不能作为摄像头、PL GCM 或物理 USB 验收。

## 2026-10-06 停止位置（历史记录）

下一项为用户首次实机 G3 验证，具体接线、命令、成功标志和日志路径见
[首次实机指南](../doc/bringup.md)。G3 通过后再运行开发态 G6。
本轮没有连接 JTAG、运行硬件服务、下载固件、读写板卡内存或写入启动介质。

G0 冷启动/LED、G7 物理故障与 2 h 长测、去 JTAG 密钥注入、板端 TRNG/DRBG、
Keccak/SHAKE FPGA 加速及最终比赛演示界面仍是后续工作；不由本轮软件验证宣告完成。

## 2026-10-07 G7 软件恢复更新

后续软件恢复改动、同 XSA 新构建目录、离线测试与 CDC 未枚举的有限实机诊断见
[G7 软件恢复记录](g7_software_recovery.md)。当前 `run_demo.ps1` 默认使用
`build/vitis/usbfix3_20261007`。坏 Tag/重放/缺片的主机恢复和错误分类已实现；
USB framing 仍 fail closed。固件 capture-status 注入不模拟真实 DMA 超时，板端计数在主机结果中
因未读取而保存为 `null`。新固件三会话 DTR 重连及接收进程强制退出后恢复已自动板测通过；
Windows PowerShell 5.1 下的 G7 基线也通过。12:36 用户完成 USB 实际拔插及接收进程异常退出各一次，
两次无需重新下载均恢复新握手和认证视频，各 471 帧、47.310/47.293 fps，摘要为 passed。
原计划各 20 次重复、摄像头故障及 DMA 超时仍待验收，G7 整体仍未完成。
