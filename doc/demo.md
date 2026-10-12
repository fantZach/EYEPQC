# 认证视频演示窗口

2026-10-07 新增。原有 `run_demo.ps1 -Mode G3/G6/G7` 入口保留。

## 不接板卡的离线演示

```powershell
& ./run_demo.ps1 -Mode Demo -Offline
```

窗口打开后点击“连接”。画面和模式栏明确显示离线/合成标记。
ML-KEM-512、Finished、命令认证、AES-GCM、重放检查和帧组装均经过软件流程；
USB 是内存字节流，GCM 和图像是软件生成，帧率不是 FPGA/实机 Benchmark。
没有串口扫描、JTAG、板卡固件加载或开发私钥文件读取；临时离线私钥仅在进程中使用。
需要已安装依赖和 M09 原生 C 库；库缺失时会用本机 GCC 构建，不生成或覆盖设备密钥。

## 已启动 G6 板卡的演示

```powershell
& ./run_demo.ps1 -Mode Demo
```

先结束独立运行的 G6/G7 接收进程，保留已预配并运行的 G6 固件，再点击“连接”。
该窗口不自动下载固件，也不写 SD/Flash；只打开一个视频 CDC 接收器。
如板卡尚未加载固件，先用现有 G6 入口初始化，再结束接收程序。
实机模式核对固件 manifest/ELF/XSA 哈希和公共密钥 pin；会话认证成功且至少解码两帧后才显示运行中。
连接或握手失败会显示错误；此入口没有自动重试物理故障，也不替代 G7。

## 按钮和统计

- “立即换钥”：发送认证 REKEY，完整排空旧会话视频，再执行新握手；比较实际视频密钥，拒绝重复。
- “篡改一包 Tag（本机）”：在主机认证前修改一个接收包的 Tag，验证该包/帧被拒绝，下一完整认证帧恢复。
  这是本机可控演示，不代表 USB 线上注入攻击。
- “开始/停止录像”：逐帧保存完整认证并解码的明文 JPEG 和时间戳，支持跨换钥录制。
- “回放录像目录”：连接期间也可点击；选定录像后窗口会先正常结束当前会话，再按记录时序播放已解密图片并逐帧校验 SHA-256。一致性哈希不是签名，回放不是再次进行 GCM 认证。
- “导出 MP4 / AVI”：对已关闭录像逐帧校验 SHA-256 并解码 JPEG 后，导出 H.264 MP4 或 MJPEG AVI；时间来自录像逐帧 elapsed。导出在后台执行，可取消；取消、校验失败或编码失败会清理临时文件，不覆盖已存在的目标。导出两遍流式读取录像，内存只保留当前帧和时间索引。
- “断开”：结束当前接收并关闭会话/串口；关闭窗口也先清理接收线程。

面板展示会话 ID、已认证完整帧、会话内平均帧率、认证失败、重放拒绝、丢帧、换钥次数和握手耗时。
失败/丢帧统计来自主机接收处理，不能据此证明板端 camera/FIFO/DMA 没有溢出；板端计数标记未读取。
预览只保留最新已认证帧，避免 GUI 队列堆积；录像保存接收器认证通过的每一帧，而不是屏幕刷新采样。

运行结果位于 `data/captures/demo_offline/<时间>/` 或 `data/captures/demo_usb/<时间>/`。
录像子目录 `recordings/<时间>/` 包含 `recording.json`、`frames.jsonl` 和编号 JPEG，也可从窗口导出 MP4/AVI。
录像 elapsed 使用 G6 协议 64 位微秒时间戳，在每个 session 首帧用主机单调时钟锚定；这是 PS 发送完整帧时采样的 XTime，不是相机曝光时间。同 session 时间戳非递增会拒绝，换钥后的新 session 可重新从零计时并锚定到原录像时间轴。两种容器保留帧间时间间隔；播放器对 AVI 时间戳的解释取决于播放器。未完整关闭的录像不作为完整录像接受。
这些目录被 Git 忽略，含解密明文，不随源码推送。

## 电脑端复核

```powershell
& ./.venv/Scripts/python.exe sim/tb/test_demo.py
& ./.venv/Scripts/python.exe sim/tb/test_g6.py
& ./.venv/Scripts/python.exe board/prj/check_demo_gui.py
```

前两项验证控制器、记录完整性及认证回调，GUI 检查需要可用桌面和 Tk，会临时打开离线窗口，
定向测试需要 GCC 在 PATH 或通过 `CC` 环境变量指定原生编译器。
自动按按钮、录像和回放；结果保存到 `build/demo_gui_result.json`，预览保存到 `build/demo_preview.png`。
最后一项不适用于没有显示服务的 CI；它不计入默认回归。`-Mode Check` 已纳入无窗口 `test_demo.py`。

`imageio-ffmpeg` 随演示依赖提供 MP4/AVI 编码器；导出会再解码整段输出并核对帧数。
电脑端压力用例使用离线合成视频、软件 ML-KEM/AES-GCM、JPEG 解码和录像逐帧写盘，不能代表 FPGA 或板卡性能。
2026-10-08 已在运行中的 `usbfix3_20261007` 固件上实测新界面、换钥/篡改、跨换钥录像、回放后重连和 MP4/AVI 导出。验收报告及持久素材在 `data/captures/demo_live_acceptance/20261008_193414_562175/`：722 个认证回调帧全部保存且 MP4/AVI 各自可完整解码 722 帧；含换钥暂停整段为 43.29fps，换钥后连续 15.122 秒片段为 47.22fps。一次演示窗口测试不替代 G7 重复故障恢复、DMA 超时或长时间硬件可靠性验收。

连接中选择回放、断开后回放、回放后重连的 GUI 自动化序列可用以下命令在合成画面下完整复核：

```powershell
$env:PATH = "C:/msys64/ucrt64/bin;$env:PATH"
& ./.venv/Scripts/python.exe board/prj/check_demo_live.py --offline-smoke --record-seconds 10 --output build/demo-live-smoke
```

只有去掉 `--offline-smoke` 才会打开板卡 USB CDC；该实机验收命令独立运行，不属于 `-Mode Check`，并应在 USB/JTAG 测试串行交接后执行：

```powershell
$env:PATH = "C:/msys64/ucrt64/bin;$env:PATH"
& ./.venv/Scripts/python.exe board/prj/check_demo_live.py --workspace build/vitis/usbfix3_20261007 --record-seconds 15
```
