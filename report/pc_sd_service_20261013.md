# PC：SD 板测服务暂停与恢复记录

时间：2026-10-13，UTC+08:00。PC 只配合转发服务与日志，不操作 JTAG、调试 COM4 或 SD。

## 当前交接状态

- 13:58:48 收到主协调者明确暂停指令后，核对 PID 29588 的完整命令行与 8765 监听归属，
  再查 8765 无 `Established`，结束该 relay 进程。事后确认 8765 已无监听。
- 8766 公共下载服务 PID 34120 保持运行，根目录精确为 `tmp/mobile_pairing/public`；
  其本机下载连接不属于手机观看会话。
- 原 token、pairing.json、pairing.txt 和公钥均未修改。Board 已获得视频 CDC 独占窗口；
  **直到 Board 完成且主协调者明确通知恢复前，不启动 relay。**
- 暂停前自动枚举：视频 CDC 为 COM7（VID 03FD/PID 7020），COM4 为 CH340 调试 UART。
  Board 切换固件后必须重新枚举，不能沿用此快照推定固件或端口正常。

原服务命令（只含文件路径，不含 token 值）：

```powershell
"C:\Users\23976\AppData\Local\Programs\Python\Python312\python.exe" -u pc/src/host/relay.py --token-file tmp/mobile_pairing/relay.token --host 10.179.236.247
"C:\Users\23976\AppData\Local\Programs\Python\Python312\python.exe" -u -m http.server 8766 --bind 10.179.236.247 --directory tmp/mobile_pairing/public
```

这些 PID 是本次快照，后续绝不能直接复制旧 PID 执行结束操作。

## 可复现步骤

在仓库根目录只读查询：

```powershell
& ./pc/run_relay.ps1 -Mode Status
Get-CimInstance Win32_Process -Filter 'ProcessId = <当前状态查询得到的PID>' -OperationTimeoutSec 5 |
    Select-Object ProcessId, CommandLine
```

只允许确认属于本项目、命令使用 `pc/src/host/relay.py` 和本项目 token-file 的进程。
不能按名称结束 Python；不能因端口占用直接结束未知进程。

前台服务正常停止：手机先停止，观察 `RELAY_STOP_DRAIN outcome=quiet` 和 `RELAY_SESSION_CLOSE`，
然后在服务终端 Ctrl+C。若无观看连接，可直接 Ctrl+C。

对于原后台进程，在收到明确暂停指令后，先重验完整命令行与监听归属、手机已停止且无 8765 观看连接，
才执行 `Stop-Process -Id <刚验证的relay PID>`，事后复查 8765 无监听。任何身份/连接变化都先报告。
这只是闲置服务停服步骤，不是活跃视频会话的正常 STOP，不构成拔线/异常恢复实板验收。
8766 可保留，不占 CDC。

等待 Board 交还设备后恢复（自动发现唯一视频 CDC，不固定 COM7）：

```powershell
& ./pc/run_relay.ps1 -Mode Run -BindAddress 10.179.236.247 2>&1 |
    Tee-Object -FilePath tmp/pc-relay-sd.log -Append
```

入口只复用现有 token，不更换配置；端口已有监听会拒绝启动。若执行策略阻止 Windows PowerShell 脚本，
可用 `powershell -NoProfile -ExecutionPolicy Bypass -File ./pc/run_relay.ps1 -Mode Run -BindAddress 10.179.236.247`
仅指定本次进程策略。服务启动仅证明监听，必须等 Board 固件准备好才让手机连接。

## 日志与配对边界

新版日志保留 STOP 排空结果并新增对端地址、串口、发送记录数/字节数、队列峰值、连接时长、异常类型及固定关闭原因。
不记录 token、控制正文、业务密钥或 JPEG。记录数包含控制/密文分片，不能当成手机 FPS。
默认应用队列上限仍为 64 条；20 ms 正超时、单个后台读取、250 ms 自然完成等待和 STOP 150 ms quiet/2 s 上限未变。
主错误原因不再被同一任务在清理时的异常误标为 USB 清理错误。

13:58 前只读核对了当前私有 JSON 与 relay.token、公钥 hex/pin 的一致性；未打印凭据。
实服务 HTTP 检查：未授权 `/stream` 返回 401；下载 `/pairing.json` 与 `/relay.token` 返回 404；
`/public.bin` 返回 200 且与本地 800 字节公钥完全一致。
公开目录仅有公钥、公钥摘要和 APK。该检查不是公钥可信来源或手机认证显示验收。

若 SD 启动保留原身份，可复用既有手机配置；若 Board 更换身份或 PC 地址变化，
用 Board 提供的**公开**目录重新导出私有 JSON，沿用当前 token：

```powershell
& ./.venv/Scripts/python.exe pc/src/host/prepare_pairing.py --identity-dir <Board交付公开目录> --endpoint ws://10.179.236.247:8765/stream --token-file tmp/mobile_pairing/relay.token --config-file tmp/mobile_pairing/pairing-sd.json
```

目标文件必须不存在。经可信途径交给手机，不放入 `public/`。PC 配对工具只读公钥与摘要；
不读/复制板端私钥，也不替手机握手或解密。故障先收集桥日志、手机错误、Board `fatal/transport/control`，
不做无依据的重复 JTAG 复位。

## 验证

- `python -m unittest discover -s pc/tests -v`：27 项通过，包括新增 USB 读失败后新会话、
  慢网络发送超时、服务关闭释放 CDC、日志无 token、入口拒绝已有监听、状态查询无需凭据。
  USB 均为模拟串口，网络为真实本机 WebSocket，不是实板/手机恢复结果。
- `python sim/tb/test_three_end.py`：1 项测试内 5 会话通过，覆盖握手、重新连接、REKEY、STOP、丢失首个 ACK；
  PC/JVM + C 模拟板/合成 JPEG，不是 SD/手机实机结果。日志位于 ignored `tmp/pc-three-end-sd.log`。
- 2026-10-13 用户已确认手机显示约 40 fps 足够；不以 PC/JVM 测量替代手机性能证据，
  不优先优化 45 fps，不宣称 G8 10 分钟长测、G7 故障恢复或 SD 冷启动通过。
- 提交时保留原四项 pre-commit hook；仅暂存 PC 与本报告，共享文档/Board/Android 改动由所属聊天处理。

未恢复转发服务，等待协调者通知；未做实板拔线/冷启动、手机长测、公网或 VPN 部署。
