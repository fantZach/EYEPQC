# G7 USB 物理拔插重复验收

更新：2026-10-08。批次目录：[`g7_batch_usb_unplug_20261008_194604_712_cece53b6`](g7_runs/g7_batch_usb_unplug_20261008_194604_712_cece53b6/)，机器汇总 [`batch_summary.json`](g7_runs/g7_batch_usb_unplug_20261008_194604_712_cece53b6/batch_summary.json)，现场窗口记录 [`operator_console.txt`](g7_runs/g7_batch_usb_unplug_20261008_194604_712_cece53b6/operator_console.txt)。

## 结果

原批次记录 20 次 USB Slave 数据线物理拔出/插回、PnP 移除/重新枚举及新会话恢复全部成功（20/20，机器 summary 为 passed）。后续审查发现其中 trial 8、14、18 的接收器在 `os.replace(result.json.tmp, result.json)` 遇到 WinError 5，result JSON 留在 `running`；stderr 最后更新时间早于首条 PnP `missing` 观测，且原运行器没有记录拔线瞬间接收器存活状态。因此三轮虽有拔插和恢复结果，但不能确认物理拔线发生时旧视频接收进程仍存活，不能计入严格 active-stream 拔线验收。原始 trial JSON 和 summary 均未改写。

原批次 trial 1–7、9–13、15–17、19–20 共 17 轮的中断结果以 `failed/SerialException/ClearCommError failed` 终态收尾，stderr 时间与首条 PnP `missing` 观测相差 -0.219～-0.981 秒；与真实 USB 断线收尾相符。三轮证据不足的时间如下（UTC）：

| 原 trial | interrupted result 最后写入 | receiver stderr 最后写入 | PnP 首次 missing | 原因 |
|---:|---|---|---|---|
| 8 | 11:48:04.811 | 11:48:04.935 | 11:48:07.570 | `atomic_write` 的 `os.replace` WinError 5；result 保持 running |
| 14 | 11:49:50.365 | 11:49:50.501 | 11:49:52.465 | 同上 |
| 18 | 11:50:39.024 | 11:50:39.114 | 11:50:41.722 | 同上 |

## 三轮替补与严格判定

修复结果写入后，单独运行 3 轮替补批次：[replacement batch](g7_runs/g7_batch_usb_unplug_replacement_20261008_200302_164_df9c80b1/)，[summary](g7_runs/g7_batch_usb_unplug_replacement_20261008_200302_164_df9c80b1/batch_summary.json)，[窗口日志](g7_runs/g7_batch_usb_unplug_replacement_20261008_200302_164_df9c80b1/operator_console.txt)。3/3 通过。新运行器在每次提示拔线前保存 worker 存活与 JSON `running` 状态；拔出后只接受与 PnP missing 时间相邻的 `ClearCommError` SerialException，并要求 interrupted result 最终写为 `failed/SerialException`。替补试次在拔线前分别已认证/解码 6、3、6 帧，旧接收器最终结果记录 172、96、184 帧；进程退出相对首次 missing 观测为 -0.706、-1.071、-0.470 秒，恢复各 93、93、94 帧。三轮的前后 `first.jpg`/`last.jpg` 共 12 张均已解码为 640×480；每轮 session/key 改变、无 JTAG 重载。PnP 是定时采样，采样时间不等同于用户拔线的精确瞬间；trial 2 有一个 present 采样晚于 receiver exit 约 79ms，但其终态 SerialException 与首次 missing 观测间隔为 -1.071 秒，仍在运行器规定范围内。

因此严格 active-stream USB 拔线验收为原批次 17 轮 + 独立替补批次 3 轮，共 20/20。40 个被采纳旧/新 session ID 和 40 个 key SHA-256 指纹互异；恢复 92～95 帧、47.182～47.511 fps，40 张首帧 JPEG 均可解码为 640×480。所有被采纳记录匹配相同 manifest/ELF/XSA。原批次机器 summary 仍保留其 20 次物理/PnP/恢复结果状态；本节严格有效数通过 17+3 原始证据另行计算，未将旧 summary 的 20/20 直接当作 active-stream 判据。

三轮原批次错误的 `PermissionError` 是主机结果 JSON 的 Windows 原子替换失败；它们是本次实测发现的主机写盘错误，不能概括为主机错误全零。`atomic_write` 已改为同目录唯一临时文件，并对 WinError 5/32/33 做最长 1.5 秒有界退避，超时仍抛出错误且保留旧目标文件。真实 Win32 `CreateFileW` reader sharing lock 离线测试验证了 0.25 秒短锁释放后写入成功，以及永久锁下有界失败且旧 JSON 完整保留；相关 G6 测试 11/11 通过。USB runner mock 同时覆盖拔线前进程已退出、原子替换失败、断线时间不匹配、结果仍为 running、PnP 歧义/超时及失败停止，均拒绝计为通过。

所有恢复结果没有填充板端 `board_statistics`（缺失/`null`）。因此这些批次证明的是主机侧 PnP 移除/枚举、重新握手、认证与图像解码恢复，不能证明板端 DMA/capture/USB 错误计数为零，也不覆盖摄像头故障或真实 DMA 超时。G7 整体及 G0 仍未通过。

## 复核方式

独立复核确认原批次恰有 20 个 trial 记录且 PnP/recovery 20/20；严格 active-stream 采用 17 个原批次终态 SerialException 记录和 3 个新替补记录。替补 JSON 另记录提示前 worker live、`running`→`failed/SerialException` 终态及 receiver exit 对 PnP missing 的时间差。综合接受集的 40 个 session ID 与 40 个 key 指纹互异；40 张首帧图像已由 Pillow 再次解码并确认尺寸。

本批次使用的是可回滚的开发态 JTAG 已加载固件；批次本身不写 SD/Flash，也不在 trial 之间重下载。历史单次拔插记录保留在 [G7 软件恢复记录](g7_software_recovery.md)，不覆盖本批次原始证据。USB 数据线的此前单次事件和本次 20 轮批次分别留档。
