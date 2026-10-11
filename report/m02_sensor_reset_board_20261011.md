# M02 摄像头实板补测：传感器复位、冷启动与 fail-closed

**状态：板上传感器复位/配置 20/20、整板断电/上电探针 20/20、无摄像头 fail-closed 均通过。**

2026-10-11 使用 `build/vivado/m02_coldboot_candidate_20261011_explore` 通过 JTAG 装载 Explore bitstream 和 PS 初始化，并在同一板卡会话中执行 20 轮传感器复位及配置。20 轮都返回 `status=00E95640`、sensor ID `0x5640`、last `0x3035`、error `0`。前 10 轮为 320×240，后 10 轮为 640×480；最后一轮使用 quality 12、VTS 2400。

本批次验证了同一次供电/JTAG 会话中的重复传感器复位与两种分辨率配置。它不是 20 次整板冷启动：整板电源没有在轮次间断开，PS/PL 由探针通过 JTAG 装载。板卡在测试结束后已恢复到经既有验收的 candidate006d；最新 Windows 枚举显示视频 CDC `03FD:7020` 为 COM16。

证据日志：`build/m02_jtag_explore_20261011.log`。本候选 bitstream SHA-256 为 `210b3eeb326a5e64961efc2e73730fa9a9548aa18af8fb4d1db346154bad9edd`，PS7 init SHA-256 为 `843f5b69dcb988b42d181a3e52c6670b95d9584aba8937afa64d516543e03380`，XSA SHA-256 为 `36d19203839d4c29a4593192d63d8fd6a5c0060812840044b80d23bd24819b3b`。

## 2026-10-11 整板断电循环与无模组门禁

用户逐轮确认完成 20 次整板完全断电/上电，每轮断电时确认板卡指示灯全灭并等待至少 10 秒，摄像头模组保持连接。每轮上电后由 `prj/run_m02_jtag.ps1` 通过 JTAG 临时加载 Explore PL/PS 并执行一次 SCCB 配置（`-SensorResets 1`），20 轮分别保存为 `build/m02_coldboot_01.log` 至 `build/m02_coldboot_20.log`。20 份日志均包含 `M02_JTAG_OK sensor_resets=1`，并返回 `status=00E95640`、OV5640 ID `0x5640`、last `0x3035`、error `0`。逐轮确认和日志 SHA-256 汇总见 `build/m02_coldboot_cycles_20261011.jsonl`，该索引 SHA-256 为 `e3d4c7daa9dc529251ba68608bf1d2c762cb33f8a94d3f09d10872046c403598`。

独立无摄像头测试在完全断电后拔下整个摄像头模组，再上电运行 `-SensorResets 1 -ExpectCameraFailure`。结果为 `configured=0`、`capture_resetn=0`、`failed=1`、`error=1`、`status=01620000`，符合 fail-closed 判据；原始日志及摘要分别为 `build/m02_camera_absent_20261011.log` 和 `.json`。

测试后再次断电、接回摄像头并通过 `build/restore_candidate006d_after_kx.tcl` 恢复 candidate006d。成功标记 `G7_CANDIDATE006D_RESTORED`、只读 JTAG 目标检查通过，Windows 视频 CDC `03FD:7020` 重新枚举为 COM16。原 SD 卡、Flash 和 eFuse 未改动。上述循环是在每次冷上电后由 JTAG 临时加载 PL/PS，不代表 SD/Flash 独立启动；本批次也未验证 DVP/JPEG 实际采集。
