# G7 USB ETW 单轮诊断采集

用途：在一次 receiver-exit 恢复尝试中，对齐 Windows USB 主机栈传输完成事件、串口 I/O 元数据和主机程序的 0 字节读取记录。它用于缩小故障边界，不会单独证明 G7 通过或确定固件根因。

## 采集范围

- 使用 Windows 自带 `logman`，provider 为 USBXHCI、UCX、USBHUB3 和 Kernel-IoTrace。
- USB provider 启用 `Default`、`HeadersBusTrace`、`StateMachine`、`Rundown`。`HeadersBusTrace`记录 USB 传输事件头但不保存 USB 数据包；不启用 `PartialDataBusTrace` 或 `FullDataBusTrace`。
- 最长 5 分钟、循环 ETL 上限 128 MB。ETL 和清单写入被 Git 忽略的 `build/g7_usb_etw/`。
- 记录会包含 USB 设备描述符、设备路径和 I/O 时间元数据。原始 ETL 留在本机，不作为普通 Git 证据提交。

## 一轮操作

1. 在**管理员 PowerShell**中进入 `work/EYEPQC`，启动采集：

   ```powershell
   .\prj\collect_g7_usb_etw.ps1 -Action Start
   ```

   脚本要求恰好一个状态正常的 `03FD:7020` CDC 设备，并在输出里显示 ETL 路径。若检查失败或设备数不符，不会启动采集。

2. 在另一个普通 PowerShell 窗口，从项目根目录运行一次候选 012 receiver-exit 测试：

   ```powershell
   .\run_g7_batch.ps1 -Mode ReceiverExit -Attempts 1 -RecoverySeconds 2 -FaultSeconds 30 -WaitCdcSeconds 20 -Workspace build/vitis/g6_secure_cleanup_20261011_candidate012_tx_ownership_r3 -HostSourceRoot .
   ```

   只跑一轮，不启动长批次。runner 在试验期间不重载 JTAG；它会记录 build identity、主机读取和板端 AP0 元数据。

3. 试验结束后回到管理员 PowerShell，停止并封存采集：

   ```powershell
   .\prj\collect_g7_usb_etw.ps1 -Action Stop
   .\prj\collect_g7_usb_etw.ps1 -Action Status
   ```

   `-rf 00:05:00` 也会限制采集时长；若超过时限，ETW 会自行停止。退出状态、ETL 字节数和完整路径写入相邻 JSON 清单。

## 判读边界

把 ETL、`trial_01_try*.json`、receiver/recovery stdout/stderr 与 AP0 前后快照按 UTC 时间对齐。重点检查：USB IN URB 的提交/完成状态和长度、设备/endpoint 标识、Windows 串口 I/O 完成时刻，以及主机读取是否仍为 0 字节。

如果设备 dTD 已完成而 USB 主机 URB 未正常完成，继续查 USB 传输/主控制器路径；如果 URB 完成但串口 I/O 仍不交付，转查 Windows `usbser`/应用句柄交接；如果两层都显示成功而应用读取仍为空，再检查用户态关闭/重开时序。单次 trace 的阴性结果只说明本轮没有捕获到相应事件，不能直接当作根因结论。

管理员权限要求和关键词语义见 [Microsoft USB ETW 采集说明](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/how-to-capture-a-usb-event-trace)。
