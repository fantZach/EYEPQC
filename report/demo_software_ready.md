# 演示系统电脑端完成记录

2026-10-07。在保留 G3/G6/G7 入口及已验证固件的基础上，新增 `-Mode Demo` 和 `-Offline`。
状态面板、认证失败/重放/丢帧统计、主动换钥、本机单包 Tag 篡改、认证帧连续录制和按时间戳回放已实现。
连接线程独占传输，Tk 仅消费事件；图像预览有界，不堆积接收记录。

## 验证

- G6 原生 C session 集成：9/9 PASS。新增回调录制测试确认坏 Tag 所在帧不进入录像，只有后续完整认证帧被保存。
- 演示后端：5/5 PASS。覆盖离线控制/录像/篡改后恢复/换钥、取消握手清理、文件篡改/路径替换拒绝、坏 Finished 无视频，以及错误公钥 pin 在端口访问前拒绝。
  离线测试将串口打开、扫描和固件读取替换成一调用即失败，保证不依赖板卡。
- Tk 桌面检查 PASS：实际按钮、统计、录像、换钥、时序回放和无回调异常；Windows DPI 适配后检查全部控件及页脚可见。
- 原有 `usbfix3_20261007` 启动/BSP/哈希预检 PASS；没有修改 PS/RTL，不需为此重建固件。
- 用户实机反馈换钥、篡改等操作可用，但实时连接时“回放录像目录”置灰。窗口现允许连接中选目录，随后先结束会话再回放；操作说明已更新。

默认完整回归新增 `test_demo.py`，现在包含 19 个入口。上次完整运行是 18/18；本轮只重跑受影响的
G6/演示测试和入口预检，没有将未重跑的 19 个入口写作全部通过。
可复核命令和记录格式见 [演示使用说明](../doc/demo.md)。

## 2026-10-07 时点边界（后续更新见 10-08）

截至 2026-10-07，本轮没有打开实机串口、JTAG 或重新加载固件。离线合成视频不是实拍，软件加密吞吐不是 PL 性能。
当时新界面的实机连接与按钮、录像写盘对实际吞吐的影响尚待验证；帧序列回放已完成，MP4/AVI 导出未实现。后续实机结果见本报告 2026-10-08 验收节。
G7 物理拔插、完整 G0、安全生产部署、板端熵源和 ML-KEM PL 加速的状态不因当时 UI 完成而改变。

## 2026-10-08：实时回放与视频导出

新增实时会话中选择录像后先停止会话再回放、后台 MP4/AVI 导出与取消；源录像逐帧哈希及 JPEG 解码通过后才交给 ffmpeg，完成后重新解码并核对帧数。目标已存在时拒绝覆盖。导出依赖锁定为 `imageio-ffmpeg==0.6.0`。

- `.venv` 下 `sim/tb/test_demo.py`：12/12 PASS。包含坏 JPEG/空录像、目标文件保护、取消编码进程回收，52 帧 VFR MP4/AVI 完整解码，以及分批回调下的相机时间戳、同会话非递增拒绝和换钥后新 session 归零。
- `.venv` 下 `prj/check_demo_gui.py`：PASS。真实 Tk 离线窗口覆盖取消文件选择保留 live、live 选录像后结束会话并回放、模拟 stop 异常不误入回放、哈希损坏拒绝、MP4/AVI 按钮导出及无 Tk 回调异常。
- 完整软件模拟流包含合成画面、软件握手/GCM、JPEG 解码和逐帧录像写盘，目标 47fps，实收 166 帧 / 5.172 秒 = 31.90fps。这是端到端软件路径的性能观察，说明绘图/密码/处理限制，不作为录像层或 FPGA 吞吐结论。
- 单独录像层压力预先生成一张 640×480 合成 JPEG，以 47Hz 写入约 10 秒，完成 471 帧 / 2,557,059 字节，47.02fps；随后逐帧核验哈希、索引和时序。该项只测主机文件写入路径，不包含实时 GCM 或相机。
- `prj/check_demo_live.py` 提供显式非 Offline 实机验收入口：控制器与 CDC 收帧、录像期间 Tag 拒绝和恢复、换钥、10–30 秒录像、连接中选片停止后回放、回放后重连，再导出 MP4/AVI 并核帧数。入口不触发 JTAG。
- 同一入口的 `--offline-smoke --record-seconds 10` 全流程已在真实 Tk + 合成软件传输下通过，报告标注 `board_accessed=false / jtag_accessed=false`。测试实际走过录制、Tag 拒绝、换钥、选片断开回放、重连和两种导出；文件帧数与认证回调录像计数相同。合成 Tk 运行只有约 16fps，此为 GUI+软件处理的诊断数据，不能当作 FPGA 或实机帧率。

### 2026-10-08 实机演示录像验收

使用已运行的 `usbfix3_20261007` G6 固件，在 USB 测试串行交接后执行以下命令；未运行 JTAG、未重载固件：

```powershell
$env:PATH = "C:/msys64/ucrt64/bin;$env:PATH"
$env:CC = 'gcc'
& ./.venv/Scripts/python.exe prj/check_demo_live.py --workspace build/vitis/usbfix3_20261007 --record-seconds 15
Remove-Item Env:CC
```

运行 `20261008_193414_562175` 全阶段 PASS：Tag 篡改后出现 1 次认证拒绝并恢复；录像中完成换钥，随后连续 15 秒收帧；连接中选录像后停止会话并回放，之后重连成功；MP4 与 AVI 均导出成功。录像保存 722 帧，认证回调数同为 722。按板端帧时间戳计算，包含换钥空档的整段为 16.654 秒、43.29fps；换钥后的无中断片段为 715 帧 / 15.122 秒 = 47.22fps。接收控制器相应 session 记录 47.26fps 和 47.27fps。两种导出独立完整解码均为 722 帧，末帧 PTS 16.654 秒，时长 16.66 秒。使用的 manifest SHA-256 为 `8363a42e…d29238db`，ELF SHA-256 为 `f4917382…f2a207453`，XSA SHA-256 为 `46de12fa…c01024`。录像、导出和完整 JSON 位于 `data/captures/demo_live_acceptance/20261008_193414_562175/`。

时间来自固件 `src/ps/src/g6_usb.c::send_frame` 对 `XTime_GetTime` 的采样，除以 `COUNTS_PER_SECOND / 1000000` 后写入 64 位微秒字段。它是 PS 发送完整帧时读取的会话单调计时值，不是相机曝光时间。每个 session 首帧用主机单调时钟锚定到录像时间轴；同 session 非递增值拒绝，换钥新 session 的时间戳归零后重新锚定。实机素材保留每帧时间间隔，包括换钥暂停。

实机验收结束后接收进程均已停止、COM16 已释放；G6 固件保持原样。该结果只验证本次 15 秒窗口和演示路径，不替代重复硬件可靠性、DMA 超时或 G7 验收。

复核命令：

```powershell
$env:PATH = "C:/msys64/ucrt64/bin;$env:PATH"
$env:CC = 'gcc'
& ./.venv/Scripts/python.exe sim/tb/test_demo.py
& ./.venv/Scripts/python.exe prj/check_demo_gui.py
Remove-Item Env:CC
```

实时验收是单独显式入口，不纳入 `-Mode Check`：

```powershell
$env:PATH = "C:/msys64/ucrt64/bin;$env:PATH"
& ./.venv/Scripts/python.exe prj/check_demo_live.py --workspace build/vitis/usbfix3_20261007 --record-seconds 15
```

实时入口会打开 G6 USB CDC、创建明文帧录像并把结果写入 `data/captures/demo_live_acceptance/`；需与其他串口/板卡测试串行执行。2026-10-08 的 15 秒实机演示已完成：722/722 回调帧写盘，MP4/AVI 均完整解码 722 帧，回放后重连成功。该短测不代表长时间录像或不同负载下的可靠性；详情见上方验收记录。

在无板环境复核完整 GUI 流程可用 `--offline-smoke --record-seconds 10 --output build/demo-live-smoke`；该模式使用合成画面且不访问串口。
