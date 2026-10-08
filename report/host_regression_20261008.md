# G6 主机与演示离线回归（2026-10-08）

## 结果

修复后的演示与 G6 主机离线回归通过。复验时 `src/host/g6_board.py` 指纹为：28,772 bytes，mtime UTC `2026-10-08T14:00:47.8603855Z`，SHA-256 `927D35695A0C87426C533F6C070054B0FCB5A3864B13308374981088BBDAF520`。

| 检查 | 结果 |
| --- | --- |
| `sim/tb/test_demo.py` | 12/12 PASS |
| `sim/tb/test_g6.py` | 11/11 PASS |
| 完整离线 GUI smoke | 8/8 阶段 PASS；Tk 回调错误 0；录制与认证回调均为 166 帧；MP4 和 AVI 均导出并解码为 166 帧 |
| G6 只读构建预检 | 62 项哈希检查 PASS；`board_accessed=false` |

单测覆盖默认离线握手、认证录像、篡改/重放拒绝与恢复、换钥、录像校验和时间戳、MP4/AVI VFR 全帧导出解码，以及取消导出清理。G6 用例还覆盖坏 Finished、分片重组、REKEY 排空及 20 次认证换钥。

离线 smoke 完成连接、录像、Tag 拒绝后恢复、录像中换钥、停止当前会话后回放、重连、MP4/AVI 导出与解码。录像回调计数与保存帧数相同。输出 JSON 标记 `board_accessed=false`、`jtag_accessed=false`，两个合成会话也均标记 `board_accessed=false`、`port_open_attempted=false`。合成画面的帧率仅反映本机软件演示，不代表 G6 板卡或实机吞吐。

## 首测问题与复验

首测时，`send_control()` 直接读取 `ser.write_timeout`。离线 `OfflineBoard` 和 G6 测试 `MemoryBoard` 未定义该字段，导致默认握手也抛出 `AttributeError`。首测 `test_demo.py` 为 12 项中 9 pass、2 fail、1 error；`test_g6.py` 为 11 项中 4 pass、7 errors。失败堆栈均指向此属性读取，演示线程因此未进入 `STREAMING`。

首测文件快照为 28,641 bytes，mtime UTC `2026-10-08T13:48:49.5279117Z`，SHA-256 `487334D86E75071ADB87E3EF0AF151C4680E87A07EB74E3B74A16E09CB957998`。修复使用 `getattr(ser, 'write_timeout', None)` 检测可选超时；未设置时沿用旧的 `flush()` 路径。复验的 23 项单测全部通过。

## 复核命令

在项目目录使用：

```powershell
$env:PATH = 'C:/msys64/ucrt64/bin;' + $env:PATH
$env:CC = 'gcc'
& ./.venv/Scripts/python.exe sim/tb/test_demo.py
& ./.venv/Scripts/python.exe sim/tb/test_g6.py
& ./.venv/Scripts/python.exe prj/check_demo_live.py --offline-smoke --record-seconds 10 --output build/demo-live-smoke-regression-20261008T1403
Remove-Item Env:CC
```

G6 只读预检：

```powershell
& ./.venv/Scripts/python.exe src/host/g6_board.py --workspace build/vitis/usbfix3_20261007 --verify-only
```

## 离线边界与产物

本轮没有打开板卡、USB CDC、UART 或 JTAG，也没有加载固件。合成软件流的回放、录像、GUI 与媒体编码结果不替代实机演示或硬件性能/可靠性验收。

离线 smoke 结果：[result.json](../build/demo-live-smoke-regression-20261008T1403/20261008_220147_201103/result.json)。录像与 MP4/AVI 保存在同一结果目录下；目录含合成视频和解密图像，仅供本机回归，不作为实机录像。
