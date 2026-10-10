# 隔离 Keccak 实板基准测试 — 2026-10-10

修复后的 `firmware_hw` 在实板上完成了 3 轮 tcId 76 ML-KEM-512 KAT 路径及 timeout 检查。三轮同启动比较中，硬件路径的端到端解封装都比软件慢，因此本加速器没有集成进正式 006d 视频构建。

## 构建身份与核验

安全构建目录为 `build/parallel_20261010/C/firmware_delivery_safe_elfs`。manifest SHA-256 为 `f43cefe3d8aca5bd19cf3e6fac728d7e6fb5982c9dda24c1f228405bc8376515`；route4k XSA SHA-256 为 `70fe149c62b3a2cc402adfb78fac625520151309015d89815576784a1fd250a2`。SW ELF SHA-256 为 `b7a4fef87820ce9da9835aef3cba6b783ad446a2097fa0cd47d707153bc20fdf`，HW ELF SHA-256 为 `08cfd5c21d25c93572692ab2ef5b458902f8339090ef8a11957135747b3e876f`。manifest 中 `board_validated=false`，实板结果由本报告单独记录。

已独立重算安全 manifest 列出的 715 个源码、生成输入、库、ELF、map、readelf/反汇编输出、bitstream 和 PS7 init 文件哈希；四份安全实板采集记录也各报告 715 项检查。较早的 `preflight.json` 对 manifest `c2b8a15f314eb3e8407722335c2fdf7715a7af49f576b89d41b1755e505ec229` 记录了 715 项检查。该哈希属于历史 20261009 构建，不是本次修复后的安全构建，因此仅作为历史证据保留，不视为当前 preflight。

实测 `counter_hz` 为 333333343，与匹配 BSP 的 `floor(666666687 / 2)` 相符。计时换算为 `seconds = raw_ticks / counter_hz`。每轮的 100 次纯软件 Keccak permutation、50 次 STATE 写加 50 次 RESULT 读传输探针、单次硬件 permutation，以及三次 ML-KEM 解封装是不同统计窗口；SW/HW 性能比只使用同一个 `firmware_hw` 启动内、各自恰好 3 次解封装的窗口。

## 同一启动内的端到端比较

每行对比同一次 `firmware_hw` 启动内的软件和硬件三次解封装窗口。比值为软件 ticks 除以硬件 ticks；小于 1 表示硬件耗时更长。

| Run | SW 3 decaps (ticks) | HW 3 decaps (ticks) | SW/HW ratio | HW slower | Timeout fallback (ticks) |
|---|---:|---:|---:|---:|---:|
| hw_safe_01 | 1079195 | 1171639 | 0.921099 | 8.57% | 1426781 |
| hw_safe_02 | 1079395 | 1173096 | 0.920125 | 8.68% | 1426611 |
| hw_safe_03 | 1078516 | 1171554 | 0.920586 | 8.63% | 1426919 |

三轮比值范围为 0.920125–0.921099，均值 0.920603；硬件慢 8.57%–8.68%，均值 8.62%。每轮正常 HW 路径均记录 96 次 dispatch、96 次硬件成功、0 次 fallback；timeout 路径均记录 96 次 dispatch、0 次硬件成功、96 次软件 fallback，且 `timeout_clear_status=00000000`。

修复后的传输探针分别计时 50 次 STATE 写与 50 次 RESULT 读，然后相加；START 到 DONE 的有界轮询在两个计时区间之外。只在 DONE 后读取 RESULT，并在读取前输出 `MMIO_TRANSFER_RESULT_READ_GATED_DONE_PASS`。timeout 清理只读取 STATUS，并输出 `TIMEOUT_STATUS_ONLY_CHECK_NO_STATE_RESULT_READBACK`；这不验证 STATE/RESULT 读回，也不构成整个设备已清零的声明。

单独的 safe 软件 ELF 也通过 tcId 76 解封装路径，记录 96 次软件 dispatch，未走硬件路径。它用于确认独立 SW ELF 的基线功能；表中的三个性能比值不跨 SW/HW ELF 比较，而取自每个 HW ELF 启动内的软件窗口。

## 无效的旧软件采集

保留的 `sw_original_01` 串口记录仅作诊断，不用于性能或 KAT 验收。其 `counter_hz=9437417530590118751`、13 位 `ticks_hi` 和损坏的 dispatch 数值不符合 32 位 Cortex-A9 的 `xil_printf` ABI。当前 parser 会拒绝该记录。对应 manifest、源码和 ELF 哈希见 JSON；旧 20261009 固件源码早于合法 RESULT 读取及 UART 格式修复，不能用于当前实板 preflight。

## 006d 恢复记录

Keccak 测试后的独立恢复结果为 `passed`：采集到 140 个脱敏帧，窗口 2.910 秒，47.77 fps（请求窗口 3.0 秒），board counters 为 null。构建哈希、来源 SHA-256 和首末帧 SHA-256 见 JSON。首次恢复记录状态为 `failed`，错误为 `FileNotFoundError` / `[WinError 2]`；当时遗漏 `--tool-root`，工具未能正确启动。随后显式指定 `E:/fpg/2026.1` 重试并通过。该问题属于工具路径配置，不是固件失败。恢复证据与 Keccak 计时相互独立。

## 复跑步骤

以下命令会进行一次临时 JTAG 实验下载；每轮使用未曾使用过的唯一 label。分别执行即可复跑 safe SW 和 HW ELF：

```powershell
python prj/run_keccak_board_benchmark.py --firmware build/parallel_20261010/C/firmware_delivery_safe_elfs --variant firmware_sw --label sw_safe_新唯一label
python prj/run_keccak_board_benchmark.py --firmware build/parallel_20261010/C/firmware_delivery_safe_elfs --variant firmware_hw --label hw_safe_新唯一label
```

实验结束后显式恢复最终 006d：

```powershell
python src/host/g6_board.py --workspace build/vitis/g6_auto_recovery_20261009_candidate006d --tool-root E:/fpg/2026.1 --seconds 3 --drain-stop --bounded-control-write
```

## 证据文件

每轮 `capture_result.json`、原始 `uart.log` 和 JTAG stdout/stderr 的仓库相对路径及 SHA-256 均列在 JSON 中。报告整理未访问硬件，也未改动历史 C-line 报告或构建 manifest。
