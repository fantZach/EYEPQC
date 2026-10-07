# G7 软件恢复准备与当前实测边界

更新：2026-10-07。此记录覆盖软件恢复准备和一次有限的 G6 硬件诊断，不代表 G7 物理验收完成。

## 本轮硬件诊断

`run_demo.ps1 -Mode JtagCheck` 只读枚举成功，目标包含 APU、两个 Cortex-A9 和 xc7z020。
随后一次 `run_demo.ps1 -Mode G6 -Seconds 30 -Show` 通过软件预检，并按现有入口执行了临时
JTAG 系统复位、bitstream/ELF 下载及 volatile DDR 开发密钥/种子注入；`provision_g6_jtag.tcl`
观察到固件 `g6_status == 1` 后返回成功。主机随后未找到 VID/PID `03FD:7020`，因此没有完成
USB CDC 打开、握手或视频接收。不得把该次诊断描述为“未下载”或“G6 主链恢复通过”。

诊断后 Windows PnP 当前无 `VID_03FD&PID_7020` 设备，无对应 COM 口；唯一 CH340 是 COM14，属于
UART，不是 G6 视频 CDC。该证据支持“初始化和预配完成，但测试 CDC 未枚举”，不能单独确定
USB 线、PHY、固件 USB 状态或连接器中的具体故障。未另开 UART reader，也没有重复下载。

## 软件改动

- 主机视频接收先验证 GCM tag，再更新 replay window、序列/帧间隙和组帧状态。坏 Tag、重放、缺片、
  错序或无效 JPEG 会拒绝当前帧，丢弃直到下一帧首个有效且已认证分片，再恢复显示/保存。
- 未认证包头不会更新 session、replay、帧号或缺帧统计。计数区分认证通过包、组帧包、Tag 失败、
  重放拒绝、序列间隙、帧间隙、丢帧和组帧错误。
- USB record framing 损坏仍直接失败并关闭当前会话；接收端不扫描猜测边界。重新运行入口会使用
  新握手。每次运行的 JSON 保存参数、manifest/ELF/XSA 哈希、失败分类、会话 ID、transcript 摘要；
  板端错误统计未读回时写 `null`。会话之间在内存中比较实际视频密钥，只写 `key_changed` 布尔值。
- 固件导出 capture/控制/transport/fatal/disconnect 计数和一次性 `g6_fault_inject`。将该标志设为 1
  只模拟一次 capture 返回错误，用于检查丢帧和重试路径；它不触发真实 DMA busy、硬件超时或复位。
  `FAULT` 仍 fail closed，需连接变化后重新等待握手；真实 DMA/摄像头/USB 故障恢复仍待板测。
- 产生零帧或一帧的运行不会打印成功，逐会话要求至少两个完整认证并解码的 JPEG。

固件由同一份 `build/vivado/g3_gui/m01.xsa` 重建到新目录
`build/vitis/software_ready_g7_20261007/`，没有覆盖历史产物。该轮入口曾指向此目录；最新默认见下文。
构建清单将错误计数和注入标志的地址/大小纳入 ELF-owned ABI。新固件仍是开发态 JTAG 预配版本。

## 离线检查

`run_demo.ps1 -Mode Preflight -Workspace build/vitis/software_ready_g7_20261007` 已通过真实 BSP 查询、
ARM 启动成员和产物哈希预检。针对性 `sim/tb/test_g6.py` 覆盖 20 次新鲜 rekey、错误 Finished 无视频、
坏 Tag/伪造头/重放/缺片后恢复、USB framing 损坏 fatal，以及零认证帧不能通过；须以本机最近一次
测试结果作为当前代码验证依据。所有视频均为合成 JPEG，USB 是内存记录流。

最终独立复核（2026-10-07）：`test_g6.py` 5/5 通过；Windows PowerShell 5.1 的
`run_g7_recovery.ps1 -CheckOnly` 通过。对交互脚本函数做离线替身检查，确认两帧就绪标记可识别、
已退出的接收进程不能当作就绪、标注人为中断时保留原来的失败状态和错误信息。此检查未访问板卡，
不替代 USB 物理拔插或接收进程异常退出的实机验收。

## 用户第三阶段入口

从仓库根目录运行：

```powershell
& ./run_g7_recovery.ps1 -CheckOnly
& ./run_demo.ps1 -Mode G7
```

入口先做新 workspace 预检。若视频 CDC 已存在，且最近一次有记录的 G6 JTAG 加载具有匹配的
manifest/ELF/XSA 哈希及至少两帧的完整接收结果，则优先复用，重新做握手而不下载。
基线 JSON 保留被引用加载记录的路径/哈希；这是前次加载证据，不是当前固件内存读回校验。
不满足复用条件或显式使用 `run_g7_recovery.ps1 -Reload` 时，才临时下载并完成 JTAG 预配，再等待 CDC 枚举；
如果缺少 `03FD:7020`，会限时等待枚举；该状态本身不能判断是否接线，超时明确记为未执行。
必须先取得至少两帧认证解码基线，才进入一次 USB 拔插和一次接收进程退出提示。后台接收器
会输出仅在两帧认证通过并解码后产生的 `G6_STREAM_READY` 标记，且须保持存活，脚本才会提示
拔插或强制结束。每次中断后启动新的主机进程、做新握手并要求至少两帧；
只有 PnP 观测到移除与重新枚举且两次恢复都成功，脚本才输出 `G7_RECOVERY_OK`。单轮记录位于
`report/g7_runs/g7_recovery_summary.json`，原始 G6 结果位于 `data/captures/g6_usb_*/result.json`。

脚本不会自动拔插，也不测试摄像头热拔插。若任一步超时、CDC 未出现、没有观察到拔除、会话重用
或帧数不足，则标记失败/未完成；不会自动批量重试。固件计数目前未由该入口读取，摘要保留 `null`。

## 用户复验及换钥修复（2026-10-07）

用户的 `g6_usb_20261007_114109_055333/result.json` 第一段已接收 1419 帧、47.302 fps，
但第二次握手报 `unexpected response during handshake`。此前 G7 的等待记录与它的构建哈希一致，
且两者都完成 JTAG 加载；等待提示不能单独证明数据线未连接。当前已识别到 COM16 视频 CDC。

主机换钥后改为持续排空旧会话视频，保留跨读取的 USB 分帧状态，待数据静默才启动新握手；
排空超时或残留不完整 record 仍失败。控制消息读取保留同次读取中的其余记录，避免多消息合并时
误报或丢消息。等待提示改为枚举状态描述。新增三项回归后，定向测试 8/8 通过。

复用现有固件的 `g6_usb_20261007_114607_691251` 两会话实测通过，分别约
47.387/47.242 fps，实际视频密钥不同。G7 的 fresh-load 基线通过；其复用路径也在
Windows PowerShell 5.1 下通过，记录 `g6_usb_20261007_115119_063679`，约 47.452 fps。
这些运行均使用 `-BaselineOnly` 或常规 G6 自动检查；当时尚未进行 USB 物理拔插或接收进程强制退出。

## USB 恢复修复及自动板测（2026-10-07 12:10）

用户第二轮 G7 的 PnP 日志 `usb_pnp_20261007_115426_365.csv` 已确认移除及重新枚举，
随后 `g6_usb_20261007_115441_360582` 在等待 BOARD_FINISHED 时超时；物理恢复未通过。
第一轮观测到移除但没有返回状态，不能据此判断用户操作或固件原因。

USBPS bus-reset 回调现在撤销 configured/DTR、清空接收环，并更新连接代数；G6 据代数变化
清除会话及 PL 临时密钥，回到 HELLO。配置或 DTR low 时，先禁用和有界 flush 数据端点，
清理旧 dTD ACTIVE/error、QH overlay 及软件游标，再用 SDK ReconfigureEp 重建队列。
仅 SET_CONFIGURATION 重置端点数据 toggle；DTR low 保留 toggle，因为主机没有同步重置它。
此前 `usbfix2_20261007` 的自动 DTR 测试仍失败，保留其失败结果，不作为修复版证据。

最终固件为同 XSA 的 `build/vitis/usbfix3_20261007`，已完成四套 ARM ELF/BOOT 构建与真实 BSP、
启动及哈希预检；默认入口已切换。定向主机测试 8/8 通过，USB helper 假 API 的四种状态检查通过，
包括 DTR 不写 toggle-reset，以及 flush/reconfigure 失败不能启用端点；此测试不模拟真实控制器。
`run_demo.ps1 -Mode Check` 已纳入该新检查。

新固件自动板测 `g6_usb_20261007_120957_072156`：坏 Finished 拒绝后恢复、连续三会话 DTR
重连通过，各 93 帧，47.454/47.227/47.235 fps，两次会话转换 `key_changed=true`。
自动强制结束一个已接收认证视频的自有接收进程后，未重下载即恢复新会话并接收 93 帧、47.449 fps，
详见 `g7_runs/auto_receiver_exit_20261007_121044_844184/result.json` 及其引用原始 G6 记录。

USB 交互现在分两步：拔出并保持，检测 missing 后再提示插回，自动等待 present；无需按 Enter。
物理拔插之后使用普通新握手，不额外注入坏 Finished。异常记录包含失败阶段及观测日志，历史失败不覆盖。
最终新固件的 USB 物理拔插仍须用户验证；上述自动测试没有进行实际拔线，G7 整体仍未通过。

Windows PowerShell 5.1 使用最新默认构建执行 `run_g7_recovery.ps1 -BaselineOnly -Seconds 2`
通过，复用本轮匹配加载且重新握手，记录 `g6_usb_20261007_121158_945356`，47.815 fps。
最后检查只有原有 `hw_server` 留存，测试接收进程均已退出，不占用 COM16。

## 用户物理拔插与接收进程退出复验（2026-10-07 12:36）

用户执行默认 `run_demo.ps1 -Mode G7`，完成单次 USB Slave 数据线拔出/插回及单次
接收子进程强制结束。`g7_runs/g7_recovery_summary.json` 的 status=passed，
usb_unplug_observed=true、usb_reenumerated=true、receiver_process_killed=true。
PnP 原始记录 `g7_runs/usb_pnp_20261007_123530_069.csv` 明确出现 present→missing→present，
没有 error/ambiguous 状态。早前未完成尝试及失败记录继续保留。

| 阶段 | 原始 G6 记录 | 完整认证帧 | fps | 是否重新 JTAG 下载 |
|---|---|---:|---:|---|
| 基线 | g6_usb_20261007_123505_458088 | 472 | 47.308 | 是 |
| USB 插回后新握手 | g6_usb_20261007_123539_470595 | 471 | 47.310 | 否 |
| 接收进程退出后新握手 | g6_usb_20261007_123604_734974 | 471 | 47.293 | 否 |

三份记录均为同一 usbfix3 构建的 manifest/ELF/XSA 哈希，已与当前产物核对；
两次恢复的 session_id 均不同于被中断的后台会话。每段首/末两张保存图片均已重新解码为
640×480，认证/组帧计数一致，没有报告接收认证错误。板端错误计数未读回，仍为 null。
USB 拔除时后台接收器自行退出，所以 usb_worker_killed_by_script_after_action=false；
接收进程异常退出阶段另明确由脚本强制终止，不将这两个字段混淆。

本次只验收上述两种故障各一次，原计划各 20 次重复、摄像头故障、真实 DMA 超时仍待验证；
G7 整体未完成，已有长期运行时长豁免保持原口径。本次复核只读取文件，不接管板卡。
