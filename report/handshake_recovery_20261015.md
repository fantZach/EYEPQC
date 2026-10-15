# 公网握手超时与拥塞恢复修复

2026-10-15，用户在Android0.7自动配对后再次报告握手超时并要求排查修复。
主聊天独占硬件；本轮修改Board/PC及定向测试，没有改业务协议、手机源码或云端SSH。

## 失败证据与原因

原 `tmp/cloud_wss_20261015_1/auto_pairing_relay_1.log` 显示账号已通过、打开COM7，
3条移动端控制仅返回1条51字节记录，19.875秒后异常关闭；不是配置GET/密码拒绝。
更早手机视频已产生QueueFull，导致非正常断连，证据原样保留。
只读AP0 DDR快照 `handshake_fix_before_metadata.log` 观察到phase_word=0、fatal=3、transport=1、control=2、
disconnects=24、capture=0；只读公开元数据，不读取密钥，且不把DDR读取当缓存一致的CPU现场。

源代码与真实C分支回归确认两处缺陷：

1. 普通开发G6发送中关闭CDC时，没有采用候选profile已有的DTR/connection_epoch断连分类，正常断连也会fatal并清除身份。
2. 开发态身份/seed清除后，后续断连清理能将FAULT改回WAIT_HELLO；仍能回应HELLO，但不能完成后续身份KEM。
   生产态原有终态保护，开发态缺少同一保护。新增回归在旧default -O0/-O3下复现失败码30，修复后通过。

PC原64记录队列在公网积压时关闭整个会话，是上述缺陷的触发条件之一；不能只重新注入密钥后宣称修复。

## 最小变更

- 普通/安全清理/候选profile共用发送失败分类：只有send_status=4、resume成功且DTR掉线或epoch变化，
  才安全清理旧业务状态、保留长期身份并等待全新握手；原地传输失败、DMA失败或清理失败仍fatal清钥。
- 已进入FAULT的任何profile均保持终态，不允许断连“复活”，不引入自动JTAG重注入或生产provider回退。
- PC先验证公开密文头，在帧首按packet_count判断原64记录队列是否能容纳整帧；不能则舍弃全帧，持续读USB。
  每批预留控制空间，控制不丢弃，控制溢出/非法记录仍关闭。剩余转发记录保持原字节，不解密/重封装GCM正文。
- 每发送至少65536字节应用记录后使用标准WebSocket Ping/Pong限制在途积压，Ping发送及Pong等待合用原5秒截止。
  只约束标准WS读取进度，不冒充业务GCM认证，不新增type或延长握手/网络期限。
- 记录video_frames_dropped/video_records_dropped；单帧超过整个64记录预算也舍弃。
  这是当前640×480 MVP的明确边界，更大分辨率前应改帧/字节预算，不能宣称任意大JPEG都能通过。

## 软件与构建

真实G6源码分支harness在default/secure_cleanup/recovery_candidate三个profile、-O0/-O3均通过；
覆盖正常断连保留身份、无断连证据/恢复失败清钥、清理失败保持FAULT，以及FAULT不可复活。
生产provider harness两优化级通过，既有候选恢复9项和secure cleanup真实头文件harness通过。
PC全套49项通过；新增在途限量后relay21项通过，最后总截止调整的定向测试再通过。
首轮控制溢出用例因批次原子语义变化失败，补回控制预检/空间预留后通过；失败日志未删除。
suite2真实C/Java软件互操作normal/rekey/timer/stop/reconnect五窗口通过，不作为实板/Android证据。

新构建 `build/vitis/g6_handshake_recovery_20261015_1`：125个BSP源文件、G6 ARM ELF构建通过；
75项文件哈希/BSP lookup/ARM startup复核通过。ELF SHA256：
`40dacc80495e4cb271189d6a27f4cffb900c3e93ef2a694d928c1998944b010a`。
检查无观看者后仅停止原PC relay，通过prepare_mobile.py易失JTAG装载一次并注入开发身份/新seed，
公开导出 `board/output/mobile_identity_recovery_20261015_1`，原公钥pin不变；没有写SD/Flash或更换账号/TLS材料。

## 真实板卡/摄像头/云端/JVM验证

| 窗口 | 认证解码帧数 | 有效跨度 | fps | 最大帧间隔 |
| --- | --- | --- | --- | --- |
| 修正版公网正常，要求30秒 | 1420 | 30.025338101秒 | 47.260084 | 0.048125501秒 |
| 强制终止客户端后重连，要求10秒 | 473 | 9.9876189秒 | 47.258511 | 0.0515231秒 |
| 65536字节/秒限速，要求35秒 | 167 | 34.937011秒 | 4.751408 | 0.3226673秒 |
| 限速结束后正常重连，要求10秒 | 474 | 10.001177秒 | 47.294433 | 0.0912735秒 |
| 最终5秒总截止版本再连，要求10秒 | 474 | 10.0090687秒 | 47.257144 | 0.0621166秒 |

所有PASS窗口均640×480、JVM退出0，逐帧GCM认证/ImageIO解码；5组首尾共10张JPEG另经Pillow verify、尺寸与SHA256对照通过。
这些fps不作为手机显示fps。

强制终止仅杀掉本轮自建JVM进程（非relay/板卡/其他进程），已捕获首张认证JPEG后再等2秒终止；
故意非零退出且未发送STOP，relay明确WebSocket1006/stop_forwarded=0，5.578秒窗口。
此后不重启板卡、不重新注入身份，直接新握手/认证视频成功；这是客户端异常退出测试，不是物理拔USB。

限速用一个只绑定127.0.0.1随机端口的临时透明TCP代理，转到真实云IP8765；限制云端→JVM的TLS字节为65536B/s（上限0.524288Mbit/s），
并缩小本机接收缓冲以触发真实背压，证书正常验证其127.0.0.1 SAN。不是Android移动网络带宽测量。
第一轮仅整帧丢弃仍在约20秒中止：94帧/19.076249秒、relay已丢554帧/4431分片、发送4,044,399应用字节。
客户端错误被原CLI归并为transport/authentication/JPEG失败，没有独立采集OkHttp根异常；
结合20秒时点和链路缓冲，怀疑保活排在积压视频后，不能将其说成已抓包证实的Ping超时。
该FAIL result/JPEG/日志保留，未计为通过，板卡没有在此失败后重刷。

加入标准WS在途限量后重跑：relay会话39.188秒、13478条USB记录、1369条网络记录/1,929,184应用字节，
video_frames_dropped=1492、video_records_dropped=12045、queue_peak=64；code1000、STOP_DRAIN quiet、error=none。
临时代理累计下行TLS1,969,103字节，上行4,826字节。低fps是此受控限速的结果，不是正常路径性能。
随后10秒正常重连约47.29fps。代理/探针全部关闭，没有公开新端口。

本机ignored证据：

- `data/captures/cloud_recovery_20261015_1/result.json` 和首尾JPEG。
- `data/captures/cloud_recovery_abort_20261015_1/recovery_result.json`，其 `_reconnect` 目录含正常结果/JPEG；中止目录只有首张图，不冒充完整采集。
- `data/captures/cloud_recovery_slow_20261015_1/result.json` 为FAIL，`_2/recovery_result.json` 为通过及后续重连结果。
- `data/captures/cloud_recovery_final_20261015_1/result.json` 为最终版本再连结果。
- `tmp/cloud_wss_20261015_1/recovery_{relay_1,relay_2,relay_3,abort_probe_1,slow_probe_1,slow_probe_2,final_probe_1}.log`。
- 限速/终止编排脚本 `tmp/probe_cloud_recovery_20261015.py`；不上传真实JPEG、私有凭据或原始采集到云端/Git。

## 交付状态与边界

最终PC relay（recovery_relay_3.log）和原SSH隧道保持运行，JVM探针均退出；自动配对公网GET再次成功。
Android0.7、账号密码、pairing公钥pin和服务地址都不变，无需重装APK或重新传JSON；请手机再次登录确认画面和重连。
SD仍为G0，不是视频自启动。未测试物理USB拔插、Android本次实际恢复、长时间或完整G8/G9；
保留真实认证/协议/硬件故障的fail-closed规则，开发态JTAG私钥/seed仍不是生产安全。
