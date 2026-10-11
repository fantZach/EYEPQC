# M02 摄像头传感器复位实板补测

**状态：20/20 次板上传感器复位与配置探针通过；整板冷启动和无摄像头 fail-closed 尚未完成。**

2026-10-11 使用 `build/vivado/m02_coldboot_candidate_20261011_explore` 通过 JTAG 装载 Explore bitstream 和 PS 初始化，并在同一板卡会话中执行 20 轮传感器复位及配置。20 轮都返回 `status=00E95640`、sensor ID `0x5640`、last `0x3035`、error `0`。前 10 轮为 320×240，后 10 轮为 640×480；最后一轮使用 quality 12、VTS 2400。

本批次验证了同一次供电/JTAG 会话中的重复传感器复位与两种分辨率配置。它不是 20 次整板冷启动：整板电源没有在轮次间断开，PS/PL 由探针通过 JTAG 装载。板卡在测试结束后已恢复到经既有验收的 candidate006d；最新 Windows 枚举显示视频 CDC `03FD:7020` 为 COM16。

证据日志：`build/m02_jtag_explore_20261011.log`。本候选 bitstream SHA-256 为 `210b3eeb326a5e64961efc2e73730fa9a9548aa18af8fb4d1db346154bad9edd`，PS7 init SHA-256 为 `843f5b69dcb988b42d181a3e52c6670b95d9584aba8937afa64d516543e03380`，XSA SHA-256 为 `36d19203839d4c29a4593192d63d8fd6a5c0060812840044b80d23bd24819b3b`。

仍需完成 20 次实际板卡断电/上电，每次单独保存启动日志；无摄像头负向场景需先完全断电，再拔下整个摄像头模组。原 SD 卡未改动，JTAG 探针不能替代 SD/Flash 独立启动验收。
