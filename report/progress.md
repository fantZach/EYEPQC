# Implementation progress

## 2026-10-15：握手超时与异常断连恢复修复

已复现开发态FAULT被断连路径复活的代码缺陷，并修复普通G6发送期间正常断连分类。
保留真实致命错误清钥/永久FAULT，正常DTR/epoch断连只退役旧业务会话，不自动重注入或复用旧业务密钥。
PC有界队列改为整帧准入/舍弃且控制不丢，标准WS Ping/Pong每64KiB限制SSH/TCP积压，未延长超时。
修正版G675项/BSP/ARM预检及易失上板通过；公网正常30秒约47.26fps，强制终止JVM后直接重连约47.26fps。
首个限速压力测试失败证据保留；补在途限量后35秒限速测试通过并重连恢复约47.29fps。
准确时长/帧数、限速方法、最终服务状态及Android/物理门禁边界见 [修复记录](handshake_recovery_20261015.md)。

## 2026-10-15：Android0.7登录后自动获取配对配置

PC从指定公开schema2文件提供同TLS端口 `/pairing.json`，复用Basic/scrypt/限速，下载不占USB或触发接管。
Android输入账号密码后自动获取、严格校验、私有保存公开配置，再连接原suite2；预填当前公网地址，可修改。
TLS/同地址约束、8KiB上限、已保存指纹防静默替换、后台取消及手动备用均保留，密码/token不持久化。
PC/移动端回归、HTTPS拒绝用例、APK和实际公网下载详见 [实施记录](auto_pairing_20261015.md)。
没有改Board/云端SSH或修复之前QueueFull/板端致命错误；手机安装/UI及实际视频仍待验，下载成功不算G8/G9。

## 2026-10-15：真实板卡经公网中转短测通过，待手机验证

G6 suite2固件75项哈希/BSP/ARM启动预检通过，JTAG易失加载成功，COM7视频USB枚举；SD/Flash未改。
JVM通过云端WSS完成真实ML-KEM、双向Finished、AES-GCM与逐帧JPEG解码：
1420帧/30.0251542秒/47.2604fps，STOP后重连474帧/10.0086845秒/47.2590fps，均640×480。
两轮正常STOP、error=none、queue_peak=4/64，四张首尾JPEG与结果哈希独立核验通过。
首轮PC应用层16,081,474字节/30.922秒，整会话平均4.1605Mbit/s；包含握手/清理，不代表峰值或手机测量。
真实PC relay和SSH隧道保持运行等待手机导入公网配对JSON；不是Android/G8/G9验收，
既有QueueFull故障与生产密钥/熵源、SD视频启动待办不因此关闭。见 [部署与实测记录](server_deployment_20261015.md)。

## 2026-10-15：Server已部署，公网隧道与WSS软件验证通过

用户授权直接连接124.70.38.245，已在实际Huawei Cloud Ubuntu24.04.4/aarch64上部署独立受限SSH2222服务，
专用非root用户/公钥、安装权限/文件等值与真实sshd -t/-T校验通过，systemd enabled/active；原SSH22不变。
PC公网2222连接在握手前关闭，云内本机banner正常、同期eth0未捕获2222 SYN；
不能确定是安全组或中间代理/网络，已请用户核对TCP2222/8765入站。
放行前尚无有效隧道；随后用户放行后专用SSH认证/-R/1459字节合成往返及五项越权拒绝均通过，
云IP证书/schema2/独立账号已准备；实际公网TLS/账号登录及模拟CDC清理五项通过。
临时探针和PC测试隧道停止，云端服务仍启用。真实板卡/手机视频、10Mbps持续吞吐及G9未验收；首次管理host key按用户授权TOFU，
未据扫描声称独立核验。没有上传私钥或业务材料，没有操作板卡，见 [实际部署记录](server_deployment_20261015.md)。

## 2026-10-14：服务器中转四端代码准备

用户恢复服务器中转，新增独立server/文件夹和聊天，P2P保留但暂停。
冻结方案为PC主动OpenSSH反向TCP隧道→云端公开端口→手机原WSS；TLS与scrypt账号仍在PC，
Board USB/suite2与Android0.6运行时无需修改。PC入口默认Plan/离线Check，Run才启动前台隧道；
server提供专用用户/公钥、仅remote forwarding/PermitListen8765的独立SSH2222配置与service。
四聊天仅修改所属文件，主聊天负责共享契约、联测和统一提交，见 [协调记录](cloud_coordination_20261014.md)。

主聊天复跑PC42项、Server16项、Android核心160/JSON52/临时KEM37及四个TLS/接管回环通过；
真实C/Java suite2经过模拟透明TCP节点的五窗口通过，原局域WSS五窗口复跑也通过。
Board本轮36项离线及M10检查通过，未操作硬件。真实Linux sshd、云端、SSH隧道、手机公网视频和G9未验收；
没有上传私钥/账号、签发实际云地址证书或启动真实服务，既有QueueFull/P2P失败不被软件PASS覆盖。

## 2026-10-14：无 TURN P2P 探针

首轮手机实测补记：用户安装后提供 answer，PC 在 DataChannel open 的45秒截止超时，
手机反馈“ICE/DTLS连接失败”，没有进入30秒负载测量，不能标记直连/吞吐通过。
Mihomo/TUN接口仍存在，根因尚未区分；不自动关代理，以免打断UU。
只读检查及原始offer缺失的证据边界见 [首轮手机记录](p2p_phone_20261014.md)。

新增独立 Windows aiortc1.15.0 / Android WebView DataChannel 探针和手动 SDP 交换说明。
本机真 DataChannel 429包逐字节校验，1秒窗口5.007288Mbps；PC三项测试与JS解析/负载检查通过，
独立 APK 构建和 v2 验签通过。首次 Windows Proactor close 挂起，改独立入口Selector后测试正常退出；
asyncio debug loop 的初轮约1.09Mbps不当吞吐通过，不能代替实际30秒手机异网测量。
未安装到手机、未实测校园网打洞、未接入账号/真实视频，也未修改板端或运行服务。
下一步用户安装“EYEPQC P2P测试”后，交换一次 offer/answer，在移动网保持前台完成30秒/5Mbps测试。
详见 [P2P 首轮试验](../doc/p2p_probe.md)。

## 2026-10-14：账号与临时 ML-KEM 实板/手机短测

新 suite2 固件已临时 JTAG 装载，真实相机/USB/WSS/账号链路通过 JVM 两轮认证解码：
1421 帧/30.0465811 秒、475 帧/10.0288435 秒，均约 47.26 fps，STOP 后重连通过。
用户在 Android 0.6 登录后报告约 45 fps，STOP/重连/手动换钥提示后反馈换钥后约 45 fps；
relay 记录手机正常 STOP 和新会话打开。准确证据见 [实机短测](account_ephemeral_board_20261014.md)。
尚未验证半小时自动换钥、双设备接管、完整 G8；SD 仍为 G0，自主视频启动及生产密钥/熵源未完成。

## 2026-10-14：上板前 debug CA 与账号材料准备

专用CA/实际IP服务端证书、受限ACL账号材料、schema2 JSON及0.6 debug APK已准备；
debug/release信任资源隔离独立通过，WSS真实准备材料在localhost/mockCDC验证成功/错误拒绝。
最终ARM预检再次通过，未启动正式服务、上板或写SD。安装文件与私有凭据路径见
[上板前准备记录](preboard_ready_20261014.md)；无生产安全或手机实测声明。

更新：2026-10-13。实施依据 `doc/steps.md`，采用 Ponytail：复用密码库与标准库，
以能运行、能比对的最小链路推进，保留必需的长度检查和认证边界。
当前工作副本的电脑端验证清单见 [电脑端构建记录](pc_build.md)；不代表 G0/G7 板卡门禁完成。

## 2026-10-13：SD 部署与三聊天协调

本轮新增账号与临时 KEM 软件：PC WSS/scrypt/显式接管、Android 登录/schema2/1785秒提前换钥、
Board suite2/临时私钥清理已实现；实际 C→模拟CDC→WSS→Java 五窗口通过，ARM 75哈希及672输入预检通过。
用户仅授权软件验证，未部署账号/CA/服务、未更新SD或实板。详情见 [软件联测](account_ephemeral_software.md)。

用户报告手机约 40 fps 正常并接受，45 fps 改为可选优化；不替代 G8 十分钟/故障完整验收。
三个独立聊天分别完成 Android 0.4 旧画面清理、Windows relay 部署诊断、G0 复位采集器修正，均提交所属文件。
板卡 SD 用读卡器识别为非系统 FAT32 卡，根目录原无 BOOT.BIN；首轮写入后摘要读回一致，未格式化或改分区。
实际 SD FSBL、SD 初始化和 FPGA 配置成功，但应用 handoff=0，没有进入 G0，冷启动失败证据保留。
共用 DDR linker 的 build-id orphan 地址零问题已修复，ARM 编译回归与新 G0 BOOT 离线检查通过，
新应用 load/exec 均为 0x00100000。19:02（UTC+8）已备份旧 BOOT 后更新单个启动文件，Flush/readback 通过；
旧文件另发现启动头 67 字节变化，原因不明，追加安全弹出/读卡器重插持久性检查。
19:10 重插后 BOOT 摘要不匹配，启动头再次变化 67 字节，持久性检查失败；该轮尚未放回板卡。
文件原样备份，只读文件系统检查未发现问题；暂停覆盖/上板，待换读卡器或空卡隔离。
随后用户授权重建另一空卡，新卡 MBR/FAT32、BOOT 写入及拔插读卡器后摘要通过。
19:29:41（UTC+8）真实 SD 成功 handoff 至 G0，BOOT_MODE=0x05、DDR/timer/READY 通过，用户确认 LED 正常闪烁。
用户本轮改为十分钟目标并授权自动回查；实际 640 秒、64 条 STAT、12800 ticks、12 次 DDR 复测，
单次 BOOT05、零故障/断线，minimum_seconds=600 离线复核通过。原始日志保留，独立结果明确十分钟用户例外。
三十分钟原要求未实测；冷启动窗口后只停主机采集，没有停止板卡。
另捕获新 baseline 后，用户按核心 PS_RST 恰好一次并确认 LED 恢复；两次 BOOT05/READY、复位后10秒 STAT/200ticks/2DDR，
本轮 8 条 STAT 零故障/断线。原全段因前置上一轮 4 条旧 STAT 返回 FAIL，原日志与失败结果保留；
明确排除仅这四条旧前缀、其余逐行保真检查后，同一严格 parser 对本轮复位测试窗通过，独立结果记录范围。
开发态 SD 自检子项按十分钟例外完成；G6 视频自主装载、生产密钥/熵源和原三十分钟覆盖仍未完成。
PC 8765 转发器保持暂停，不把 G0 无视频 CDC 当故障；Android 0.4 手机安装/操作未复测。
准确镜像摘要、失败根因和供电依据见 [SD 板端报告](board_sd_deployment_20261013.md)，
职责与安全恢复边界见 [协调记录](sd_coordination_20261013.md)。

## 2026-10-13：Android 单 JSON 导入

按用户要求，将 endpoint/token/公钥/pin 合并到私有 `pairing.json`。Android 0.3 使用一个文件选择按钮自动读取和校验，
无需手填或单选公钥，校验后点击连接。PC 配对工具生成 JSON，已有服务可沿用原令牌导出；当前配置已生成并通过跨语言解析。
原 Android 158 项、JSON 30 项（含实际配置31项）、PC 配对7项通过，0.3 APK完整构建与旧证书验签通过。
凭据 JSON 不放公开下载目录，Git忽略且审阅包排除。手机文件选择器/导入实际运行待验，详见 [本轮记录](mobile_json_pairing_20261013.md)。

## 2026-10-13：实板装载、PC 服务与手机配对准备

用户报告初版已安装。代理临时 JTAG 装载 G6，视频 CDC COM7 实际枚举，准备公开公钥下载、私有配对文件和校园网密文桥。
同源 Java/OkHttp→桥→真实 OV5640/PL GCM/DMA/USB 接收多轮 640×480 JPEG 约 47.26～47.28 fps，保存首末图片。
同时发现停止/重连失败，保留零帧 FAIL 和关闭异常，修正 PC STOP 排空/Windows 读取取消顺序及 Android HELLO 重试。
其后 ARM 调试访问失败，用户断电重启后再次装载，最终版本两个连续 30 秒会话通过，停止排空/再握手成功，约 47.26 fps。
最终只读诊断 fatal/control/transport=0，板端 WAIT_HELLO；完整手机显示、十分钟与 G8 仍待独立记录。
已生成可覆盖初版的 Android 0.2。准确窗口/失败/接入边界见 [实机准备记录](mobile_live_bringup_20261013.md)。

## 2026-10-13：三端 MVP 源码与软件互操作

三 agent 并行实现：板端新布局 G6 软件重建和公开身份/provision-only 入口，Windows 密文 WebSocket 桥，
Android 原生 Java 应用与 ML-KEM/GCM 会话内核。板端 73 项预检、6 项 mock；PC 桥 9 项回环测试；
Android 内核 147 项断言（含 25 ML-KEM 与 20 GCM KAT）通过。主协调者跨真实 Java/OkHttp、WebSocket 桥和
板端 C 会话/ML-KEM 的四次合成 JPEG 认证互操作通过，含新连接、重连、认证 REKEY 与 STOP，图像 SHA-256 与参考一致。
修正换钥窗口中旧视频排队导致新握手被关闭的问题，STOP 流程确认实际发送后关闭。
Android 调试 APK 正式构建与签名/清单核验通过；当前未访问板卡或安装手机，真机与 G8/G9 待验。
准确版本、哈希、证据与工具构建状态见 [推进记录](three_end_mvp.md)，准备/启动见 [运行指南](../doc/three_end_mvp.md)。

## 2026-10-12：Windows / Android 平台条件与三 agent 协作

用户确认 PC 为 Windows、移动端为 Android，并授权三个 agent 并行协作。
板端 agent 只读核对 USB/会话接口，PC agent 负责 `pc/README.md`，Android agent 负责 `mobile/README.md`；
主协调者统一修改 README、architecture、goals、steps 与本记录，集中检查和提交。
平台约束已落实到 M16/M17：Windows CDC/网络桥、Android 前台单观看端认证解密显示，
Android 框架、最低版本和密码库仍待实施时确定。组网 VPN 保留为可选路径，供应商和校园网连通/吞吐未验证。
板端继续 Standalone/USB Slave，共享 v1 格式不变；未新增网络服务、Android 应用或硬件操作。
本次仅说明与计划更新，执行文档差异/链接检查及既有提交 hook；不重复全量 RTL/板测回归。

## 2026-10-12：开发板 / PC / 移动端目录拆分

用户确认 USB Slave→PC 联网→移动端解密路线。源码归属调整为：`board/src/{rtl,ps,third_party}`、
`board/prj/` 和 `pc/src/host/`，新增 `mobile/README.md` 定义接入职责与验收。
根 README、三子项目说明、`doc/goals.md`、`doc/steps.md`、`doc/protocol.md` 与新 `doc/architecture.md`
明确局域网先行、可选公网中转（归 PC 子项目维护）、单观看端、手机端握手与解密、PC 原样转发以及开发密钥边界。
新增 M16～M19 / G8～G9 计划，板端以太网保持最后可选项。

本次没有实现网络服务或移动端应用，也没有访问板卡。保留 PC 解密演示作为互操作参考；
`sim/`、标准向量、Python 环境和根 PowerShell 入口共享。同步修正 Python 导入/仓库根定位、
PowerShell/Tcl 源码路径、RTL 初始化文件路径及测试/文档命令；审阅包包含新目录的源码，仍拒绝本地密钥、
output/vendor 等材料。第三方库和开源 AES 核只移动位置，未修改内容或许可证。

历史报告内的旧路径与哈希保留，不改写旧构建清单或板测证据；旧 XSA/ELF/manifest 需在新输出目录重建并预检，
不得将旧候选直接标为新布局已上板。G0/G7 及生产安全的待验状态保持不变。

验证记录：

- 首次广回归（`sim/tb` 加 3 个 Keccak 解析/runner 测试文件）在第 6 个失败处停止：151 passed、9 skipped、99 subtests passed，281.26 秒。
  原因分别为 candidate009 本地 SDK/BSP 缺失（1 项）、两项 Keccak 仿真的默认工具路径仍指向旧机器 E 盘、
  三项 USB SDK 测试缺少本地临时根目录。9 个 skip 为 candidate006d 本地构建不存在，不能视作通过。
- 显式使用本机 `EYEPQC_TOOL_ROOT=D:/AmdDesignTools/2026.1`，补跑两项 Keccak XSim、USB recovery 和三个解析/runner 文件：
  22 passed、7 subtests passed，11.71 秒；补齐忽略目录后 USB SDK 的 3 项测试通过（1.09 秒），未放宽哈希检查。
- 审阅包三目录准入/敏感文件排除回归：9 passed、41 subtests passed（0.13 秒）。
- Python 编译检查、所有仓库入口/板端 PowerShell 语法检查、固定依赖检查和 G6 `--help` 通过；
  构建/主机源码中 276 个完整字面量路径引用存在，29 份当前说明中的相对 Markdown 链接均存在。

本轮未完成全绿的全量回归：candidate009 fixture 检查仍受本地缺失产物阻塞；未重建 bitstream/ELF、未上板、未测试手机或公网。
提交前快速 hook 仍仅 M00/M10/M12/G5，不增加全量回归到每次提交。
本轮 `git hook run pre-commit` 四项全部通过（约 3.4 秒），暂存空白检查通过。

## 2026-10-11：G6 生产 profile 软件隔离

G6 生产 profile 已隔离开发 JTAG mailbox 与 host-seed 路径；加入 HMAC_DRBG-SHA-256、256-bit strength 输入长度门禁、1024 次重播种和失败关闭。DRBG 只编入显式生产配置，开发态仍保留原 mailbox 路径；NIST 无附加输入、additional_input/personalization、成功重播种共五组输出及失败注入定向通过。生产安全清理与自动恢复诊断已拆分，builder 单独编入 `G6_SECURE_CLEANUP` 和哈希记录的有界 USBPS overlay；最新 XC7Z020 ARM `g6s16` production ELF/link map 含受限 DMA/GCM/frame/TX 清理路径，并在 manifest 记录 TX、HELLO/ACK、session、DRBG 的链接地址/尺寸；不编入应用侧 ML-KEM decapsulation。production provider 接口只暴露公钥与 opaque decapsulation；builder 硬门禁拒绝私钥导出、开发 mailbox/seed 和应用侧 ML-KEM 符号，并要求 DRBG/provider/secure-cleanup 符号全部进入 ELF。启动路径已收口到单一生产入口，修复了重复 CDC 初始化；生产进入 `FAULT` 后即使 USB 断开也保持终态，不再回到 provider/DRBG 已关闭的 `WAIT_HELLO`。harness 覆盖 opaque-key 身份检查、provider 失败后共享秘密覆写及调用前输出清零、启动失败清理；另修复 SHA/HMAC/HKDF 无效参数遗留旧输出、session 无效重初始化、格式错误 Finished/command、序号错误和 Finished/nonce 拒绝后输出或活动密钥残留的路径，原有 7 个 fail-closed C API 回归用例通过，本轮新增 replay-window 覆盖，该文件现有 8 项。优化编译 `-O0/-O3` 的生产 profile harness 均通过。manifest 驱动的只读 AP0 读回仅输出归零布尔值，覆盖帧/密文/TX、session 临时密钥/计数器及 HELLO/ACK 缓存；当前 mock 验证通过，实板读回待做。AMD 资料确认 Zynq-7000 无应用层片上 RNG；provider 契约要求经评估的 PL 或外部源，PL 源还必须进入认证启动链。本轮全量 `sim/tb` pytest **163/163 通过**（313.64 秒，89 subtests，无警告）；G6 定向回归 **12 passed、4 subtests**。主机 `HostSession.verify_board_finished()` 对畸形控制帧也会关闭会话并覆盖旧 key buffer，新增回归已通过。M09/M10 JTAG 测试器改用一次性请求/输入/回复文件，退出前覆写删除；初次私钥装载失败也会尝试 AP0 清理，fake-XSDB 路径测试通过。审阅包策略将 `board/output/` 整目录硬拒绝，ZIP 校验测试会拦截该目录条目。M09 测试 keyset 改为公钥/pin 先原子替换、私钥最后提交；不完整 keyset 被封装流程拒绝。生产候选仍使用 fail-closed 临时 provider，`board_validated=false`。生产安全仍未通过：真实熵源/provider、密钥服务、持久化与生命周期、secure boot/JTAG、PS/PL/DDR/DMA/USB 清零读回及 host 不可控副本仍未闭环。细节见[实施记录](production_security_profile_20261011.md)。

## 2026-10-11：主机敏感文件可覆写读取

`src/host/transient_file.py` 新增有大小上限的 `read_mutable_file()`，M09/M10 板测工具用它直接将私钥和 JTAG 回复读入可覆写 `bytearray`，减少不可覆写 Python `bytes` 中间副本。定向测试验证了缓冲可覆写及超限拒绝；完整 `sim/tb` 回归 163/163 通过（313.64 秒，89 subtests）。这只是主机端秘密副本生命周期收紧，Python/密码库内部临时副本仍不可控；真实 provider、熵源与 AP0 实板清零读回未验收。

G6 USB 验收运行器也改为有界可覆写私钥读取。`prepare_demo.py` 改用 M09 的私钥最后提交事务，并清除生成种子、私钥、封装 coins 和共享秘密；当先前中断留下公钥/pin 但未提交私钥时，可以安全重试。新增回归覆盖该重试与各拥有缓冲清零。

另修复 G6 JTAG provisioning 将临时 32 字节随机种子文件直接删除的问题：现改为临时文件退出时覆写、flush/fsync 后删除，同时清掉内存种子。Fake XSDB 回归检查读取值正确，并在删除钩子处确认文件内容已归零。

G6 JTAG 的 ELF-owned private-key、seed、ready 和 status DDR 区域现在在 Python runner 与 Tcl 两端都做非重叠校验；模拟重叠地址时 runner 在调用 XSDB 前拒绝，Vivado `xtclsh` 也输出拒绝信息且未进入 provisioning。

M09/M10 JTAG 的 mailbox、私钥和输出 DDR 区域也加入 builder、Python runner 与 Tcl 三层非重叠门禁。单测验证重叠/无效长度拒绝；Vivado `xtclsh` 对两份 Tcl 的合成重叠地址均在连接前拒绝。全量 `sim/tb` 回归 **163/163 通过**（313.64 秒，89 subtests）。实际 ELF 地址、AP0 清零读回和板卡行为仍待现场验证。

## 2026-10-11：G6 开发态终态密钥清理

开发 profile 进入不可恢复 `FAULT` 时，`mark_fault()` 会覆写 PS RAM 中的 ML-KEM 测试私钥、随机 seed、JTAG provisioning mailbox 与随机计数器，并清除 ready 标志。认证失败、致命传输错误和安全清理失败共用此路径；正常 USB 断连、STOP/REKEY 可恢复到 `WAIT_HELLO`，因此仍保留已装载材料。实际 G6 源码 harness 对默认/candidate cleanup 两种配置及 `-O0/-O3` 均通过，验证终态清零和恢复路径保留；全量 `sim/tb` 为 163/163，通过 89 subtests，耗时 313.64 秒。该证据未覆盖 cache、DDR 读回或板卡行为。

## 2026-10-11：完整电脑端回归 19/19

最新 `run_demo.ps1 -Mode Check` 19 个门禁全部通过，M04/M05 使用原生 XSim；运行器记录 `board_accessed=false`。该次代码基线为 `bb212bc5a134228e6fed7223331bc9e2c2c2063a`，不是 candidate014 上板证据。逐项耗时和原始结果 hash 见[脱敏回归报告](software_regression_20261011.md)与[JSON 摘要](software_regression_20261011.json)。本轮没有访问硬件。

## 2026-10-11：candidate014 HELLO_ACK 安全重试完成离线准备

针对 candidate012 receiver-exit 中两次 HELLO_ACK 超时，candidate014 让固件对相同 HELLO 重放缓存 ACK，主机最多重发两次原样 HELLO；超时后若 decoder 留有半帧则停止重试，避免新旧记录拼接。构建、197 项文件哈希预检、G6 离线测试 25/25、G7 runner 测试 9/9、项目级 M04/M05 补测及 20 轮软件 Mock 均通过。candidate014 尚未下载到板卡，`board_validated=false`；candidate012 的 13 个通过轮不折算。代码和报告已推送 GitHub；下一步需要同候选板上基线、ETW/AP0 单轮和从零 20/20 receiver-exit，之后才进行物理 USB 拔插门禁。该轮没有访问板卡、SD、Flash 或 eFuse。详见 [candidate012 实板诊断](g7_candidate012_tx_ownership_board_20261011.md)、[candidate014 离线报告](g7_candidate014_safe_hello_ack_retry_offline_20261011.md) 和 [下一阶段计划](next_stage_plan.md)。

## 2026-10-11：提交材料与官方规则核验

candidate014 文档、验收材料、脱敏审阅包生成器及本轮规则核验记录已推送到 GitHub `main`。审阅 ZIP 和机器证据索引已按该提交在本机重建校验，但仍是团队审阅稿，不是正式比赛上传包。本机 `.gitattributes` 保留未暂存修改。官方公开页面确认 2026-11-04 18:00 作品截止时间；AMD FPGA 赛道的正式格式/评分文件与队伍资格仍待官网或队长后台确认。竞赛官网检索到的 MP4/PDF/RAR 容量规定属于芯片应用赛道，不移用到 FPGA 赛道。细节见[官方规则核验记录](contest_rules_review_20261011.md)和[交付计划](submission_delivery_plan_20261010.md)。

## 2026-10-11：candidate011 receiver-exit 实板单轮失败

用户重新插拔后 CDC COM16 与只读 JTAG 枚举恢复。candidate011 两个构建各自通过 JTAG 加载后的 2 帧认证视频基线。首个 receiver-exit 单轮在旧进程解出 7 帧后，新 receiver 等待 HELLO_ACK 超时；板端 HELLO/ACK 计数各增加 1、ACK send status=0、错误计数为 0。新增无载荷 RX/framing 诊断后重新构建，启动阶段再次超时：39 次串口读取共 0 字节，decoder 缓冲为 0；板端只读快照仍显示 HELLO/ACK send status=0。该结果排除主机收到半帧后卡在 decoder 的解释，但未确认 EP1 IN 实际数据交付。两批均 fail-stop，未跑 20 轮或物理拔插批次。详见 [candidate011 实板报告](g7_candidate011_receiver_exit_board_20261011.md) 和[机器摘要](g7_candidate011_receiver_exit_board_20261011.json)。

板测后 candidate006d 已通过带成功标记的 JTAG 恢复且 COM16 在枚举；恢复过程中一次 FTDI I/O 错误后，只读 JTAG 检查恢复，再试成功。它的旧 manifest 与当前 `src/ps/src/g3_camera.c` 不一致，主机预检拒绝该旧 build，因此恢复后的认证视频未复测。RX/framing 诊断和新构建已完成；下一步核查 EP1 IN 完成事件与 `tx_ready` 来源、DTR 低电平端点 quiesce/rebuild 顺序，修正后从单轮门禁重新开始。G7 仍未通过。

## 2026-10-11：M02 物理冷启动与无摄像头门禁完成

在先前同会话 sensor reset/config 20/20 的基础上，用户逐轮确认 20 次整板完全断电/上电；每轮 JTAG 临时装载 Explore 候选并单次配置，20/20 返回 ID `0x5640`、状态 `00E95640`、error=0。独立的断电拔除摄像头模组测试返回 `configured=0`、`capture_resetn=0`、`failed=1`、`error=1`，fail-closed 通过。20 份独立日志和索引见 [M02 实板报告](m02_sensor_reset_board_20261011.md)。之后 candidate006d 恢复成功，JTAG 目标和 CDC COM16 可见；没有复测认证视频。此门禁不代表 SD/Flash 独立启动或 DVP/JPEG 实拍。

## 2026-10-11：M02 同会话传感器探针与 KX41 全量实板 KAT（M02 后续冷启动见上节）

M02 Explore 候选先在同一板卡会话完成 20/20 次传感器复位/配置探针；后续 20 次整板断电/上电和无模组 fail-closed 已完成，详见上节。KX41 新候选三个窗口各 60/60 ML-KEM-512 KAT 通过，硬件窗口的计时为软件的 88.6%；采集器已修正为等待真实的 `KX41_BENCH_DONE` 标记。两项临时测试后均恢复 candidate006d，视频 CDC `03FD:7020` 重新枚举 COM16。详细记录见 [KX41 实板报告](keccak_sponge_x4_capture_fix_20261011.md) 和 [M02 实板报告](m02_sensor_reset_board_20261011.md)。

## 2026-10-10 续推进：身份核验优化、逐次 KAT 与 CPU 临时协议数据清理

独立 Keccak 后端把重复 ID/version MMIO 检查移至每次 configure，核验失败只 fallback；通用逐次检查 API 保留。新固件每个窗口的三次 tcId 76 解封装均检查预期输出，并将校验计入 SW/HW 对称计时。三次独立硬件启动、每次 715 项 hash 预检及 96/96 hardware dispatch 通过；强制 timeout 的 96/96 fallback 和 STATUS0 通过。新窗口 HW 仍慢约 8.4%，不宣称加速，不与旧窗口做精确因果比较；主要 MMIO 搬运开销仍约 17.1 us。见 [新板测](keccak_identity_cached_20261010.md)。

G6 新增 CPU 本地控制分发 helper，在非零输入（含部分失败/越界）处理后清整个 1036 字节缓冲；空输入不重复擦写。握手缓存消费/退出后清理，长期设备 key/seed 与防重放状态保持既有语义，不碰消费者仍可能拥有的 USB TX/DMA 明文缓冲。真实 C helper harness 通过，candidate007 独立 ARM 构建/183 项预检及有限反汇编审阅完成；实板两会话各 3 秒共 284 帧、坏 Finished 拒绝、STOP/drain 回归通过。仅支持所列对象及功能范围，不证明实板全域清零；见 [安全实施](security_cleanup_20261010.md)。

最终恢复旧 006d：在冻结源码副本逐项恢复原 manifest 精确字节（含历史混合换行），180 项预检通过后临时 JTAG 加载，3 秒复测 140 帧/47.551 fps。COM16/COM14 正常，receiver已退出；不写 SD/Flash/eFuse。旧 006d 的现场验收不迁移为新 candidate007 的完整 G7 证据。技术报告草稿也已更新事实和证据链接。G0、G7 剩余门禁和生产熵/密钥/全域清零仍未闭环。

## 2026-10-10：Keccak 实板功能、负收益 Benchmark 与交付准备

用户明确本轮先做加速器和安全/交付工作；无需等待本轮 G0/G7 物理动作。独立 Keccak route4k 在 xc7z020 板上完成 SW 1 轮、HW 3 轮：ID/version、tc76 ML-KEM KAT、每轮 96 次真实硬件置换（无 fallback）及 watchdog timeout 后 96 次软件 fallback 均通过。实测 timer 333333343 Hz；完整解封装 HW 约 1.172 ms、SW 约 1.079 ms，HW 慢约 8.6%。MMIO 搬运开销约 17.2 us/置换，因此本版没有加速收益，不接入正式视频工程。

实板前发现实验固件在未 DONE/清理后读不可访问寄存器，及新版 BSP 的 xil_printf 把 %l 按64位取参导致 Cortex-A9 32位参数错位；已修复实验源码并另建 safe_elfs，不覆盖旧产物。timeout 只合法读 STATUS 清零，不宣称全部 STATE/RESULT 读回清零。原 SW 日志输出损坏，保留诊断身份并拒绝性能分类。

板测结束恢复原 006d，COM16 3 秒认证视频与 STOP/drain/DTR close 通过。首次恢复命令缺 tool-root，在 JTAG 前 WinError2；更正实际 E:/fpg/2026.1 后成功，没有用户物理动作或 SD/Flash 写入。当前结果见 [实板报告](keccak_board_benchmark_20261010.md)。生产安全源码审阅、实施路线和公开资料索引完成；源码/脱敏证据审阅包生成器、逐文件哈希与隔离 fixture 完成，见 [安全计划](production_security_plan_20261010.md)、[交付计划](submission_delivery_plan_20261010.md)。可信板端熵源、生产私钥存储、全域清零及正式比赛规则仍未闭环。

上一批 19 文件提交 556a659 已在权限环境恢复后正常 push 到 GitHub；本轮新增实验与交付文件继续单独提交。以下保留先前上传失败及修复过程的历史状态。

## 2026-10-10：USB 修复完成、同构建恢复批次与 GitHub 整理

最终 candidate006d/v4 已完成共享 SETUP gate、两方向有界 quiesce、静态回复缓冲区所有权、QH 第二 cache line 的 SETUP 保留及标准/CDC 类错误处理。ARM 编译链接及 180 项哈希检查通过；本轮 USB host mock 3/3、G6 11/11、Benchmark fixture 12/12 和仓库要求的 M00/M10/M12/G5 检查通过。

2026-10-09 实板短测 471 帧、47.3579 fps；同一 manifest/ELF/XSA 的 camera-reset 与 routing-stall 各 20/20，通过本轮逐轮只读审核。每批首次加载、恢复无 JTAG 重载；新 HELLO、session/key novelty、认证帧及故障计数器差值均核实。这里是受控 PL 故障与真实 S2MM Busy 达到约 3 秒软件 deadline；不是硬件 timeout IRQ 或物理传感器拔除。

G7 整体尚未通过：最终 006d 的 PC 退出/DTR 20 次与物理 USB 拔插 20 次待测，旧 usbfix3 批次不能代替。G0 仍缺 SD 独立启动、物理复位及 30 分钟冷启动；原 SD 卡保持原样。此处的 Keccak 与生产安全状态是 2026-10-10 当时记录；其后 KX41 60/60 独立候选 KAT 已通过，但生产安全仍未闭环。2026-10-10 当时 GitHub 上传尚未完成；随后恢复授权并完成推送，当前 GitHub 状态见本页 2026-10-11 更新和[规则核验/交付计划](submission_delivery_plan_20261010.md)。以下按日期保留历史过程，旧的“修复中/板测暂停”描述不代表最新状态。

## 2026-10-09：离线交付整合与验收边界

B 线完成 G0 工具/manifest 的离线复核、固定来源脱敏 Benchmark 汇总和现场验收矩阵；独立 fixture 单测 12/12 通过，汇总包含 10 条独立证据记录。G0 final2 既有临时 JTAG 局部证据通过离线复验，但 SD 独立启动、物理复位和 30 分钟断电冷启动仍未通过。本轮用户确认没有读卡器，板上 SD 卡保持原样、不写入。

C 线完成独立 Keccak route4k PS+PL 工程、匹配 XSA/bitstream 及 software/hardware 两种 A9 固件的离线构建。实现地址为 `0x43C10000–0x43C10FFF`，与 M01 AES 地址不重叠；时序、DRC、资源和 manifest 哈希已复核。没有板级启动、MMIO 或性能数据，因此尚不能宣称加速收益。

G7 当前不作整体通过结论：candidate004 USB 枚举失败；candidate005 只完成离线冻结/构建、未上板。随后只读审查发现 `usb_probe.c` 的 class SETUP 路径绕过 EP0 所有权 gate：`GET_LINE_CODING` 将静态 `line_coding` 交给 IN dTD，后续 `SET_LINE_CODING` DATA_RX 可能在旧 IN 事务尚未 quiesce 时覆盖同一缓冲区。candidate006 正在补共同 SETUP gate、类请求发送/状态错误处理和 line_pending 时序测试，板测暂停。用户拔插后旧 usbfix3 基线恢复 COM16 和认证视频（记录约 47.36 fps），不据此归因于主机原因。受控 PL/DMA 故障与长录由 A 独占板卡执行。详见 [统一验收矩阵](acceptance_matrix_20261009.md)、[B 线交付](parallel_B_20261009.md)、[C 线交付](parallel_C_20261009.md) 和 [Benchmark 汇总](benchmark_summary_20261009.md)。

## 2026-10-08：演示验收、重复恢复及隔离候选

实机演示录像/回放/MP4/AVI 15 秒短测通过，722/722 帧保存并完整解码。接收程序异常退出恢复
20/20，USB 物理拔插严格有效 20 次（原17+替补3）。G0 临时 JTAG、LED 和30秒局部
DDR/定时器通过，SD独立启动、物理复位和30分钟冷启动仍未验收。Keccak独立RTL/AXI、
驱动及完整ML-KEM调用链mock通过，未接入正式板端视频链路。

摄像头/DMA自动恢复候选已有单轮受控故障成功，但最新candidate7的routing-stall尝试在
基线收帧阶段失败；随后一次usbfix3恢复未找到CDC。SDK无界ATDTW轮询排查线索、当前v3
有界USB overlay及成功/失败脱敏摘要见 [本轮同步记录](github_sync_20261008.md)。
旧成功记录不作为当前候选完整验收；本次GitHub整理不操作板卡。下文保留各轮历史过程记录。

## 2026-10-07：演示界面与录像

新增状态统计、主动换钥、本机单包 Tag 篡改、连续认证 JPEG 录制及定时回放；支持明确标注的
离线合成模式和复用 G6 固件的实机模式。G6 9/9、演示 5/5 和实际 Tk 窗口检查通过；
本轮未访问板卡，新 UI 的实机操作/录像吞吐未验收。见 [演示完成记录](demo_software_ready.md)。

## 2026-10-07：USB 恢复软件修复

当前默认构建为 `build/vitis/usbfix3_20261007`。USB bus-reset、旧队列清理和 DTR 保留数据 toggle
已补齐；主机控制消息合并、换钥排空及坏帧恢复已有回归覆盖。新固件的三会话 DTR 重连和接收进程
强制退出后恢复通过自动板测，约 47 fps。12:36 用户完成同构建的 USB 实际拔插及接收进程异常退出，
两次均无重新下载而恢复新握手和认证视频，各 471 帧、47.310/47.293 fps；
`report/g7_runs/g7_recovery_summary.json` 为 passed。两种故障各验证一次；摄像头故障、DMA 超时及
原计划各 20 次的重复可靠性仍未验收，不认定 G7 整体通过。
详细证据和操作步骤见 [G7 软件恢复记录](g7_software_recovery.md)。

## 2026-10-07：用户电脑/板卡主链复现

调试端口恢复后，新 `software_ready_20261007` 的 G3 单帧实拍、GCM 认证解密、逐字节比较和
邮箱清零通过；捕获记录 `g3_20261007_105102_021734` 的 `board_validated=true`。
用户随后完成两轮 G6 双会话短测，共 1891 帧、640×480、约 47.165～47.418 fps；
保存首/末帧均可解码。对应记录为 `g6_usb_20261007_105248_130303` 和
`g6_usb_20261007_105521_095807`。这补上了当前主链复现证据，不替代 G0/G7。
对照最初八个工作包的剩余任务与具体软件缺口见 [目标差距核对](goal_gap_audit.md)。

## 2026-10-07：G3 固件就绪超时（已修正并复测）

首次当前镜像 G3 复验在启动邮箱阶段超时，未产生采集/加密结果。
发现四个应用/FSBL 误链接通用 CRT，已采用 AMD Xilinx.spec 修正，并新增预检启动来源检查。
该轮默认目录改为 `build/vitis/software_ready_20261007`，新镜像离线构建与预检通过，
后续用户实机复测已通过；详细诊断、保留证据和验证边界见 [软件交付记录](software_ready.md)。

## 2026-10-06：ZYNQ-7020 本地构建复核（历史记录）

**同日软件阶段后续更新：** M04/M05 原生 XSim 本轮已全部通过；新脚本从同一 XSA 生成
经典 BSP，并完成 G3/G4/G5/G6 四套 ARM 固件、匹配 FSBL 和四份 `BOOT.BIN`。
修正经典/SDT BSP 的 DMA/UART 配置查找与 USB 中断适配；G6 内存 USB 集成测试覆盖
20 次软件换钥、清零、坏 Finished、篡改和重放拒绝。当前交付目录改为
`build/vitis/software_ready`，旧 `g3_delivery` 保留为历史产物。
详情与当前停止位置见 [软件阶段交付](software_ready.md) 和 [首次实机指南](../doc/bringup.md)。
下文当日早期“XSim 失败/尚无 BOOT.BIN”是已保留的过程记录；当前以此补记和软件交付记录为准。
没有实机下载，`board_validated=false`；G0/G7 和设备级密钥/熵源/Keccak 加速未完成。

用户照片可读到正点原子领航者 ATK-DIY7010/7020P 底板、CF7010B/7020B 核心板和 ZYNQ 7020 标签；
摄像头为 ATK-MC5640 V1.2。该实物与本次 XSA 的 `xc7z020clg400-2` 目标一致，首次下载仍须通过 JTAG 核对器件 IDCODE。
已有 GUI 构建截图显示 bitstream 写入完成；本地 XSA、IP、时序和 DRC 报告均已核对。
当前布线报告 WNS=+0.013 ns、WHS=+0.018 ns，用户约束满足；DRC 仍有 warning/advisory，包含 OV5640 PCLK
由 W14 经非专用时钟路由到 BUFG、且通过 `CLOCK_DEDICATED_ROUTE FALSE` 放行的 `PLCK-12`，需在板级时钟评估中保留。
从该 XSA 生成 A9 Standalone BSP，编译 BSP 驱动并归档 `libxil.a`；G3 应用以 Vitis ARM GCC 的
`-O3 -Werror` 编译、链接成功。编译时发现并修正 G3 UART 配置查询误传基地址的问题。
ELF 为 ARM ELF32，三个 DDR 共享缓冲符号的大小、64 字节对齐和地址范围已核查；bitstream、
PS 初始化脚本、ELF、源码哈希及 XSA 哈希组成的本地清单位于 Git 忽略的 `build/vitis/g3_delivery`，
详见 [电脑端构建记录](pc_build.md)。本轮 M00/M08/M09/M10/M12/G3 主机/G5 检查通过；M04/M05
XSim 构建受 Vivado 随附 GCC 6.2 无法启动影响，若干其他 Icarus 13 用例异常退出。本轮没有执行板卡下载或实拍复测，
新清单明确 `board_validated=false`；G0/G7 及未完成的整机门禁仍未通过。

## 当前状态

| 步骤 | 状态 | 产物/证据 |
|---|---|---|
| 立即清单 1：目录与忽略规则 | 完成 | src/rtl、src/ps、src/host、sim、data、board、report、skill；build 生成目录已创建并忽略 |
| 立即清单 2：官方资料与工具 | 源码研究完成，实物待确认 | 已提取 8 个官方工程并记录压缩包 SHA-256；XPR/BD 为 2020.2、xc7z020clg400-2；发现 DDR3/DDR3L 配置差异 |
| M00：协议与黄金参考 | 完成（主机离线验证） | C/Python 协议实现、标准/随机/篡改向量、独立 GHASH 中间值和复现脚本 |
| M01 / G0 | 部分上板通过、门禁未通过 | UART、DDR、定时器已验证；USB0 从机独立探针 30 秒 16.37 MB/s、30016 块逐字节正确；LED/冷启动及 USB 视频整机仍待验收，见 [USB 探针](../doc/usb_probe.md) |
| M06 / 固定图片 MVP | M06 判据完成；PS/PL 混合图片 MVP 已上板通过 | GitHub secworks/aes、AXI4-Lite、PL AES / PS GHASH；13 向量、同 Key 连续块/更新/硬复位通过，53 周期/块；IP 综合 2600 LUT/2566 FF/0 BRAM；完整 JPG/512 KiB PNG 认证往返通过；非 M08 全 PL |
| M02：SCCB 摄像头配置 | RTL/仿真/实现、同会话传感器复位 20/20、20 次整板断电/上电后的 JTAG 配置 20/20、无模组 fail-closed 均通过 | 用户逐轮确认全断电；每轮 ID=5640、error=0；负向结果保持 configured/capture_resetn=0。SD/Flash 独立启动和 DVP/JPEG 实拍仍未测；逐轮摘要见 [M02 报告](m02_sensor_reset_board_20261011.md) |
| M03：DVP/JPEG 采集 | 独立仿真/OOC 综合通过，M05 集成实拍通过 | 仿真 1000 帧逐字节及故障恢复；与 M04/DMA 集成后上板实拍 1000 帧，未单独完成 DVP 输入 IO 时序验收 |
| M04：异步 FIFO/AXIS | 原生仿真/OOC 综合通过，M05 集成实拍通过 | 三配置各 1000 帧仿真；与 M03/DMA 集成后上板实拍 1000 帧，无丢帧/溢出；默认 64 KiB 帧上限 |
| M05 / G1 功能判据 | 完成 | 缓存开关各 10000 次 DMA 和错误恢复通过；OV5640 1000 帧实拍、末帧 JPEG 解码通过；平均 6277.23 bytes、最大 6331 bytes、约 7.48 fps |
| M07：GF(2¹²⁸)/GHASH | 独立 RTL/仿真/OOC 综合完成，已被 M08 复用 | 32 组 GF 乘法、80 组 M00 轨迹和 20 组 NIST 向量逐块通过；891 LUT/1037 FF、0 BRAM/DSP |
| M08：AES-GCM AXIS IP | RTL/仿真/OOC 综合及 G2/G3 DMA 上板完成 | 102 组端到端、随机背压及异常/零化通过；6370 LUT/5679 FF、0 BRAM/DSP（OOC） |
| G2：固定 DDR→DMA→M08→DMA→DDR | 完成 | 21 组 0～1400 字节板测与主机黄金参考、认证解密一致；S2MM 延迟启动形成背压；布线 WNS +0.107 ns、WHS +0.044 ns，见 [G2](../doc/g2.md) |
| G3：实拍 JPEG→DDR→M08→DDR | 功能及板端 45 fps 目标完成 | 快速模式 1000 帧 320×240：47.172 fps；1000 帧 640×480：47.168 fps；均无计数丢帧/溢出，末帧认证解密、画面可辨；新布线 WNS +0.013 ns、WHS +0.018 ns，见 [G3](../doc/g3.md)。USB 端到端视频仍待 G4/G5。 |
| M09：ML-KEM-512 PS 基线 | 完成离线及 A9 上板 | mlkem-native v1.3.0；PC ACVP 25/25/10 组、A9 3×1000 次；Decaps 约 11.929 ms、7.953 M 周期、栈约 12,860 B、堆 0，见 [M09](../doc/m09.md) |
| M10 | 离线与 JTAG 板测完成 | 双向 Finished、认证重协商、重放拒绝和清零通过；真实 USB 控制握手待 M11/G6，见 [M10](../doc/m10.md) |
| M12 离线回放 | 完成离线部分 | 实拍 G3 多包密文认证解密、JPEG 解码/保存及篡改/截断拒绝；实时 USB 接收仍待接入，见 [M12](../doc/m12.md) |
| M11 USB 视频 / G4 | 明文门禁通过 | 固定内容先通过；摄像头 USB 连续 1799.953 秒、85064 帧、47.258 fps，逐包校验并逐帧解码；实时显示/重连通过，见 [G4/G5](../doc/g4_g5.md) |
| M11/M12 / G5 | 固定测试密钥门禁通过 | PL AES-GCM 完整 40-byte AAD，60 秒 2835 帧、47.270 fps；主机每包认证后显示，真实板端包篡改副本拒绝，见 [G4/G5](../doc/g4_g5.md) |
| M11/M12 / G6 | 开发态功能通过 | 真实 USB ML-KEM 握手、认证视频、换钥与 DTR 重连通过；JTAG 测试密钥/种子不是生产安全方案，见 [G6](../doc/g6.md) |
| C-KX41 全 60 组 ML-KEM-512 | 独立候选三窗口实板 KAT/性能通过 | software、hardware、timeout fallback 各 60/60；正常硬件零回退、timeout STATUS 60/60 清零，硬件窗口耗时为软件的 88.6%；仅限隔离 KX41 工程，见 [验收报告](keccak_sponge_x4_capture_fix_20261011.md) |
| G7 长期运行 | 用户例外验收 | 原 2 小时要求获时长豁免；实际最后可核实约 50 分钟、141777 帧、47.259 fps，未跑满 2 小时、无完整结果 JSON |
| G7 故障 / M13～M15 | 部分实机通过 | USB 实际拔插、PC 接收进程异常退出各一次通过，新握手后各 471 帧、约 47.3 fps；各 20 次重复、摄像头异常及 DMA 超时仍待验收，G7 整体及整机验收仍待完成，M14 不启动 |

2026-09-29 USB 方案变更：用户连接 USB Slave 后，CF7020B 经 JTAG 运行 CDC ACM 探针，
Windows 枚举为 COM7；30.047 秒收到 491,782,144 字节完整校验块（16.367 MB/s），
无序号或字节错误。`doc/goals.md`、`doc/steps.md`、`doc/protocol.md` 已将第一版传输
改为 USB0 字节流，历史以太网例程与验收记录保留作参考。G4/G5 实拍 USB
链路已通过；G6 开发态功能通过，G7 长期运行由用户例外验收，故障子项和完整 G0 仍待验收。

板级资料已解压并完成源码研究；用户已提供 DDR 型号/颗数，新增原理图已核对。
已临时 JTAG 下载并采集 COM4；用户确认 PS 网口未连接，G0 网络和冷启动验收保留待办。
M00 与官方研究已提交为 `e649634`；M01 为 `1a05778`，不包含官方例程或生成产物。
本次按用户要求改写 `doc/steps.md` 优先级，先完成不依赖网口/摄像头的图片 AES MVP，
复现与当前验证状态见 [图片 MVP](../doc/aes_mvp.md)。

最新顺序调整（2026-09-27）：用户要求以太网配置放到 `doc/steps.md` 最后编程阶段。
PS GEM/PHY/IP、接线、ping/echo、M11、M12 联网接入及 G4～G7 统一后置；
当前 M02～M09 独立实现及 G2/G3 功能判据已完成；接下来推进 M10 本地验证、
M12 离线回放，网络配置仍后置。
未接网口不再阻塞独立模块编写/仿真；LED/复位/冷启动要求保留，完整 G0 仍未通过。
已启动的 `m01_g0_reset_1` 仅作本地复位修正基线重建，不下载网络程序、不改网卡或 SD。

## 已实现

- 网络字节序的 40 字节 UDP 包头，1400 字节最大载荷、2 MiB 最大 JPEG、精确分片/数据报检查。
- 12 字节 Nonce（32 位 epoch + 64 位 sequence）；12 字节 TCP 控制前缀及各类消息长度限制。
- TCP 拆包/粘包、保留位、版本、套件、错误码与 UTF-8 校验；默认禁止明文视频降级。
- 可移植 C99 序列化与解析，不需要 OS、动态内存或非对齐结构体访问。
- cryptography AES-GCM，加密/认证解密与独立 GF(2^128)/GHASH 逐块模型。
- kyber-py 离线 FIPS 203 参考，固定测试种子与内部 Encaps 输入，可复现 KeyGen/Encaps/Decaps。

M00 的格式验证不是完整会话安全实现。KDF/Finished/命令 MAC/重放窗口在协议文档中约定，
具体状态机待 M10/M11；组帧、认证后显示和回放待 M12。Python KEM 教育库不用于生产握手。

## 验证记录

环境：Windows，Python 3.12.10；cryptography 48.0.0、kyber-py 1.2.0、
cffi 2.1.1、pycparser 3.0；主机 gcc 16.1.0。

运行 `sim/scripts/run_m00.ps1`：5 份向量文件与 SHA-256 清单可复现，10 项测试全部通过。
覆盖 20 组 NIST AES-GCM（AES-128/96-bit IV/128-bit Tag）；
NIST ACVP v1.1.0.35 的 ML-KEM-512 KeyGen 25、Encaps 25、Decaps 10，含隐式拒绝测试。
固定 SHAKE256 测试输入生成 56 组边界与 24 组随机 AES-GCM 向量，
39 组保存的篡改样本，另逐位翻转一个 17 字节明文、40 字节 AAD 样本的
Key/Nonce/AAD/密文/Tag，共 808 次认证失败检查。
1000 组随机包头通过 C/Python 字节比对，包含不对齐输入/输出、32/64 位数值、明文/加密及尾片。
包括标准向量数量与哈希、EOF 半包、超长消息、截断数据报、UTF-8 和缓冲区容量检查。

C 使用 `-std=c99 -Wall -Wextra -Werror -pedantic` 编译通过；
也使用本机 Vitis `arm-none-eabi-gcc` 以 `-mcpu=cortex-a9 -marm` 编译为 ARM 裸机对象通过。
这是协议模块的编译验证，不代表已生成/运行完整裸机应用。
`pip check` 通过。测试时间仅代表主机软件自检，不作为 PL/网络性能结果。

NIST 原始 GCM ZIP 请求遭 HTTP 403/传输失败，导入脚本使用 pyca 上游保存的原始 CAVP `.rsp`，
固定提交 `8e03e30e3aae01632a697e903e3593c924f0139d` 并核对 SHA-256。
ML-KEM 直接取 NIST ACVP 提交 `65370b861b96efd30dfe0daae607bde26a78a5c8`，
原始 URL、文件哈希和筛选结果见 `data/kat/sources.json`。

## M01 实现与待完成门禁

用户提供的资料实际位于资料包内的 `4_Source_Code` 子目录。
已读取压缩包索引与源码说明，发现 `1_FPGA_Design/ZYNQ_7020_FPGA.rar`（1,519,052,295 字节）
和 `2_Embedded_Vitis/ZYNQ_Vitis_7020.rar`（2,249,047,175 字节）。
包含 `42_ov5640_udp_pc`、`1_hello_world`、`8_uart_intr_loop`、`9_timer_intr_led`、
`40_lwip_echo_server`、`44_ov5640_ps_eth_udp_pc`；源码说明标注从 2018.3 升级到 2020.2。
已通过 `prj/import_vendor.ps1` 提取 30 个 FPGA、2237 个 Vitis 文件，清单全部存在。
详见 [官方例程研究](vendor_examples.md)，核心结论：

- hello/echo 等配置 DDR3L MT41K；camera 配置 DDR3 MT41J，不能混用未经实物确认的 PS 配置。
- 两个摄像头工程的引脚一致；PCLK 约束为 25/72 MHz，仍需按实际模组配置测量。
- FPGA42 是 RGB565/PL 网络；Vitis44 的初始化确实启用 JPEG/PS GEM。
- Video In 的 TLAST 是 HREF 行结束，不是 JPEG EOI；必须补 M03/M04 帧级边界与错误恢复。
- camera 示例存在 SCCB 无 ACK 检查、DMA 1031/UDP 1024 长度不一致、缓存维护顺序及错误恢复问题。
- 旧生成 DMA 长度位宽为 14，不能容纳 2 MiB 整帧；simple DMA 的实际长度可从完成后的 S2MM_LENGTH 读取，后续先仿真/短包验证。

资料研究阶段原始官方源码未改写，也未下载实物板卡；后续 JTAG/COM4 验证见下文。
官方 SCCB/采集两个独立 RTL 顶层的 Icarus 语法/展开检查通过（不是功能仿真）。
M00/官方研究提交前 hook 通过，M00 10 项测试通过。

本次新增，详细说明见 [M01 构建与上板](../doc/m01.md)：

- `prj/build_m01.ps1/.tcl/.py`：独立 PS7 BD、100 MHz PL LED 心跳、同步复位、实现/XSA、
  Vitis Python Standalone/lwIP 构建；全新目录，不覆盖旧产物，不下载板卡。
- `src/ps/src/m01.c`：UART、统一状态/始终启用的应用断言、异常、SCU tick 与全局计时器检查；
  64 KiB 自有 DDR scratch 的非缓存/缓存读写；周期自检与统计；静态 IPv4 ping/TCP echo。
- echo 检查完整 pbuf 链，发送空间不足时保留给 lwIP 重试，处理 FIN 关闭重试及连接计数。
- `src/host/m01_probe.py`：标准库 echo 长包/分段读/重连探针，默认 1800 秒；失败不静默重试。
- `sim/scripts/run_m01.ps1`：四项离线测试通过（含实际 PHY C 模型）；M00 十项回归通过；pre-commit 增加 M01 校验。

历史构建（补装前）：Vivado 2026.1 识别有效 BASIC 许可证，但 `get_parts xc7z020clg400-2`
为空，安装目录缺少 Zynq-7000 器件支持。脚本在创建项目之前明确失败，未用其他器件替代。
当时没有新 BD 验证、综合、实现时序、bitstream 或 M01 XSA 的成功结果。

为继续软件验证，单独提取官方 echo 的 `vitis/system_wrapper.xsa` 到忽略的 `build/reference/`，
SHA-256 为 `0e27f6285f61cd8b56d7f3bf2fa2da309ce8ad1f87a20d2796d59709650f43d6`。
实际运行 Vitis Python 脚本成功建立 Standalone、lwIP 2.2.0 BSP、FSBL 和 M01 Cortex-A9 ELF，
应用 `-Wall -Wextra -Werror` 编译通过；上游 BSP/旧 XSA 生成代码仍有警告，不当作板级通过。
最终参考工作区 `build/vitis/m01_reference_final/`，清单记录输入/源码/ELF 哈希。
参考 ELF 的 DDR scratch 起始 `0x00200080`、64 KiB，与栈及其他 BSS 分离。
DDR 测试只覆盖 scratch，不是全内存压力测试；应用测试和 localhost 探针不代表真实网口通过。

后续实际验证（2026-09-27）：用户已安装 Zynq-7000 器件支持，
`get_parts xc7z020clg400-2` 成功；两颗 H5TC4G63EFR-RDA 配为 1 GiB / 32-bit、
Custom DDR3L-1066、CL8/CWL6。独立新工程 `m01_hynix_sd` 的 BD、综合、实现、
bitstream/XSA、对应 Standalone/lwIP BSP/FSBL/ELF 全部成功，未回退到参考 XSA。
PL 时序 WNS 6.068 ns / WHS 0.130 ns / WPWS 4.146 ns，DRC 0 项；
25 LUT、60 FF、0 BRAM/DSP，LED 外部 output-delay 提示仍留存。
SD0 及 setup/hold 失败检查已加入并验证；新 FSBL 实际链接 `InitSD` 与同平台
`ps7_init`，新 ELF scratch 为 `0x00200080` / 64 KiB，与其他对象和堆栈分离。
产物哈希见 M01 文档，清单 `board_validated=false`，未创建/写入 BOOT.BIN。
应用继续使用 BSP/lwIP，按 Ponytail 不引入新驱动框架或依赖。

新增硬件资料包已核对，核心板 V2.5
原理图标明 DDR 1.35 V；图中 PS PHY 为 YT8521SC-CA，而旧官方/新 AMD lwIP
均无对应型号分支，不能盲用 Marvell 初始化。原理图、走线 CSV 与哈希见
[官方例程研究第 7 节](vendor_examples.md)。用户确认 CF7020B / COM4；规格书可对应
该型号，但不等同于已经确认 PCB 为 V2.5。实际 MDIO 读到 YT8521 `0000:011A` / 地址 7；
已加入双 ID 分派、铜口/电平校验、RGMII 延迟和有界 reset/协商，不改官方源码或全局 BSP。
临时 JTAG 下载成功，UART 启动、64 KiB DDR scratch 非缓存/缓存及 60 秒复测通过，
50 ms tick 正常；已采集至应用 sec=70，DDR/异常/断言/滞后均为零。网络 PHY link=0，
未通过 ping/echo，LED 频率仍需实物确认。当前 PC 网卡与开发板静态网段不一致，
与板卡静态 192.168.1.10 不同网段，未擅自修改网络设置。

原定下一步：确认 PS 网口接线/地址 → 实际 ping/echo、LED 验证 →
基于同平台 SD 冷启动运行 30 分钟 → 确认 G0 后进入 M02。
已易失性 JTAG 下载；未写 SD/Flash。用户确认 PS 网口未连接，协商超时符合当前接线状态。
最终软件为 `m01_cf7020b_v2`，原始日志/输出哈希见 M01 文档。

## 提前执行：M06 / 图片 AES MVP

用户于 2026-09-27 要求先完成 AES 加密图片，并采用 GitHub 开源核。
复用 `secworks/aes` 提交 `80dc4718e1dcbbdb4b0dd1bdb393d8f7b98981dc`，
保留 BSD-2-Clause/原始版权；接口固定 AES-128 Encrypt。原生 GP0/AXI 协议转换器
连接最小 AXI4-Lite 寄存器，PS 调度实际 PL AES，PS 软件 GHASH 保留完整 GCM 认证。
无新依赖、摄像头、DMA、网络、ML-KEM 或非易失启动写入。

独立 RTL 仿真：1 个 NIST AES 块与 12 个确定性随机块，通道错开/背压、WSTRB、
非法访问、忙时拒写与上游轮密钥/状态零化通过。实际可移植 C 模块对照 80 个 M00、
20 个 NIST GCM、5 个长输入向量通过；主机 mailbox 认证、超长/截断与故障清理通过。

首次 `aes_mvp_1` 原生 BD/综合/实现/XSA/ELF 构建成功，100 MHz 时序通过，
但上板和一次断电重试在启动后 DAP 超时，未取得图片加密结果。
生成 reset IP 明确显示辅助复位 `C_AUX_RESET_HIGH=0`，输入却接常量 0，
导致 PL 永久复位；旧 M01 的 UART/DDR/定时器结果不受此问题影响，
但从未通过的 PL LED 实测不能据此认定成功。
共享板级 Tcl 已显式配置外部低有效、辅助高有效并增加实际 BD 属性断言；
M01 离线测试增加极性配置回归（共 5 项）。修正硬件 `aes_mvp_2` 已构建并上板验证。
旧 M01 硬件也需要重新构建后再验收 G0；其历史产物和日志保留，不覆盖。

原 64 KiB ELF 已在 CF7020B 上实际完成：9373 字节 PNG 两次运行、65536 字节上限 PNG 一次，
独立主机认证解密与原文件逐字节及 SHA-256 一致，五类篡改均被拒绝。
用户新提供的 JPG 为 365954 字节；软件缓冲区扩至 512 KiB，复用已验证 bit/XSA，
只重新构建 `aes_mvp_3` 软件。空闲/JTAG 时禁用 DCache，PS 独占处理时启用，
完成后刷新/关闭再发布结果；不压缩、不裁剪原图。完整 JPG 实测通过，全部字节及 SHA-256
一致：`f7ebf2bd3af8a998c5afd155982faa576be6bc8e1babde5ec1dfb2b7f19d5650`。
板端近似耗时 4652657 us（不含 JTAG 传输），五类篡改拒绝、板端密钥/Nonce 零化检查通过。
512 KiB 合法 PNG 上限也实测通过，板端近似耗时 6820005 us。
日志/清单/图片保存在 Git 忽略的 `data/captures/aes_mvp_userjpg_1/`、
`aes_mvp_boundary_512k/` 和 `aes_mvp_userjpg_uart_1.log`，完整复现及产物哈希见 MVP 文档。
Vivado 100 MHz 时序 WNS 0.767 ns / WHS 0.089 ns，2987 LUT / 3094 FF，无 BRAM/DSP。
无摄像头/网口/全 PL GHASH 或视频吞吐验收，G0 和正式后续门禁仍未通过。

### MVP 性能优化

用户要求优化 4.65 秒的板端处理。未换 AES 核或重建硬件；Vitis 明确启用并核对 `-O2`，
GHASH 改为固定循环的 32-bit 字运算，无秘密索引表或未对齐整数强转。
同一原始 JPG：`-O0` 4652657 us → `-O2`/byte GHASH 512107 us →
`-O2`/word GHASH 首次 239584 us。AES/MMIO 调用 22875 次约 51039 us，
PS 其余约 188544 us（含 GHASH/CTR/XOR/初始化/探针，不是纯 GHASH）；仍不是 15 fps 验收。
第一轮软件 `build/vitis/aes_mvp_o2_word_1`，构建清单新增真实优化级别与构建脚本哈希；
旧记录保留。同图三次 239584 / 239072 / 239584 us，中位数 239584 us，约快 19.42 倍，
板端约 12.22 Mbps / 同等大小 4.17 张每秒；不是视频或 15 fps 验收。
512 KiB 上限 342481 us，也通过认证、密文/Tag/全部字节比对、SHA-256、五类篡改与密钥清理。
原始 JPG 未压缩/裁剪；105 组离线黄金向量及全部 18 项 hook 检查通过。
日志为 `data/captures/aes_mvp_word_profile_uart_1.log`，结果为 `aes_mvp_word_jpg_1..3/`
和 `aes_mvp_word_boundary_1/`，均 Git 忽略；复现/计时边界见 MVP 文档。

第二轮仅将应用及 C 黄金向量检查改为 `-O3`，实际编译命令已核对；PS C/RTL 不变。
ARM 反汇编确认 GHASH 的 4-word 内层移位循环展开，主循环仍固定 128 次；
ELF text 增加 1008 字节，data/bss 不变，无新依赖、秘密索引表或手写汇编。
同图三次 153440 / 153437 / 153401 us，中位数 153437 us，比第一轮再快 1.56 倍，
比最初快 30.32 倍；AES/MMIO 49984 us、PS 其余 103453 us，不含 JTAG/最终缓存刷新。
板端约 19.08 Mbps / 同等大小 6.52 张每秒，仍未通过 15 fps 或完整视频验收。
512 KiB 上限 219779 us；四次认证/全部字节/SHA-256/五类篡改/板端密钥清理均通过。
105 组 C 黄金向量及全部 18 项 hook 检查通过，当前软件 `build/vitis/aes_mvp_o3_word_1`。
证据为 `data/captures/aes_mvp_o3_profile_uart_1.log`、`aes_mvp_o3_jpg_1..3/`、
`aes_mvp_o3_boundary_1/`，不提交图片、日志或密钥；第一轮历史产物保留。

## 复现

```powershell
& ./sim/scripts/run_m00.ps1
& ./prj/check_environment.ps1 -ToolRoot 'D:/AmdDesignTools/2026.1'
& 'D:/AmdDesignTools/2026.1/gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe' -mcpu=cortex-a9 -marm -std=c99 -Wall -Wextra -Werror -pedantic -I src/ps/include -c src/ps/src/protocol.c -o build/vitis/protocol.o
```

新工作区请先按 README 建立 Python 环境，并创建忽略的 `build/vitis` 后执行交叉编译。

## Git 提交前校验

已加入 `.githooks/pre-commit`，本仓库设置 `core.hooksPath=.githooks`。
hook 顺序为暂存改动空白检查、生成向量一致性检查、M00 10 项测试。
实际执行 `git hook run pre-commit` 通过；注入不存在的 C 编译器后返回非零并拒绝提交。
当前顺序为暂存空白检查、向量一致性、M00 10 项、M01 5 项、图片 MVP 3 项、M02 4 项、M03 2 项和 M04 1 项离线测试。
M04 调用已安装 Vivado 的 XSim/XPM 原生模型，没有工具时明确失败，不以简化 FIFO 替代。
hook 校验工作区文件，不自动暂存、生成向量或创建 Git 提交；本次按用户要求暂存并提交图片 MVP。

## M02：代码/仿真与最小上板探针

`tb_heartbeat.sv` 曾移至 `sim/board/`，现按用户最新要求移回 `sim/tb/`，M01 原有回归不删除。
重写最小开漏 SCCB，复用官方 camera44 的 251 个有序寄存器事实，不复制旧 SCCB 驱动。
OV5640 先读 5640 ID，配置后检查 16 项关键寄存器；失败保持摄像头/采集复位。
支持分辨率、量化参数、HTS/VTS、JPEG/YUYV；时钟、超时、上电/复位延迟均可校准。
4 项离线检查覆盖引脚协议、来源事实、20 次模拟初始化、错误 ID/NACK/超时/读回篡改、
重配置/输入锁存与复位恢复、板级 GPIO 参数/状态映射。
独立综合 `m02_synth_1`：421 LUT / 250 FF，无 latch/BRAM/DSP；开漏 IOBUF 2 个，0 综合警告/错误。
模块的 OOC 综合会转换开漏 tri-state，已调整摄像头 BD 为整体综合，不将错误分块产物用于上板。
用户先确认摄像头未接、只做代码仿真，随后确认已连接；最小探针已实现/临时 JTAG 下载。
P2/上拉/IO 引脚已核对原理图，实际模组晶振不能由传感器资料确认；暂不驱动 W15 XCLK，
通过真实 ID/配置结果继续确认。不改网络、SD/Flash，也不把 GPIO 配置成功等同于 JPEG 采集通过。
完整接口、来源、命令和剩余物理门禁见 [M02](../doc/m02.md)。
有效硬件 `m02_board_2`：WNS 0.787 ns / WHS 0.051 ns / WPWS 4.146 ns，
882 LUT / 1082 FF，无 latch/BRAM/DSP，DRC 0 项，原生 SCCB IOBUF 2 个。
首次 run 0..6 ID/配置成功，run 7 在 4300 回读发生超时，保护正确退出；
未擅自增大超时或把该失败删除。复测同版硬件 run 0..19 全部通过，包含两个 JPEG 分辨率、
质量/VTS 切换，ID=5640；日志 `build/m02_board_2_jtag.log`、`m02_board_2_jtag_retry.log` 保留。
xsdb.bat 在 Tcl 报错后仍可能退出 0，新增最小 PowerShell 包装器验证本次成功标志，
离线注入零退出假失败的检查通过。首次间歇超时仍需 ILA 定位；真正断电冷启动 20 次、
JPEG 采集/FPS/PCLK 均未通过，未写 SD/Flash、未运行网络程序。

用户再次要求上板：复用同版/同哈希硬件及正式 PowerShell 包装器，
`build/m02_board_validation_20260927_1.log` 的独立首批 20/20 完整通过，
ID=5640、16 项关键回读、320×240/640×480 JPEG 和质量/VTS 切换均正常。
重复验证时本助手未等待第二个 XSDB 完全退出便启动第三个，导致两个会话重叠复位/访问；
`..._2.log` AP0 读回中断，`..._3.log` ps7_init/DAP 报错，这两批无效，不计入通过数。
所有相关进程已退出，后续访问严格串行；原生 DAP 复位恢复了 ARM 枚举但不能停核，
系统/核组复位仍超时（`..._4.log`、`..._5.log`、`..._dap_reset_2.log`、`..._core_reset.log`）。
用户已断电重启，ARM 调试恢复；随后严格串行执行两批，各 20/20，共 40/40 次传感器配置通过。
新日志 `build/m02_board_validation_20260927_after_power_1.log` 与 `..._after_power_2.log` 均有本次成功标志，
每次 ID=5640、error=0、16 项回读通过，覆盖两个 JPEG 分辨率及末次量化参数 12/VTS 2400。
这只有一次板卡断电重启，不是 20 次实物冷启动；历史 4300 超时未复现但尚未定位，完整 M02/G1 未通过。
没有改 RTL/参数、新增依赖、写 SD/Flash 或运行网络程序；详细日志哈希见 M02 文档。

## M03：按 steps 推进采集模块

用户撤回临时快照优先，恢复 M03 → M04 → M05 顺序；未建立 BRAM/JTAG 摄像头快照旁路。
新增 `dvp_capture.sv` 与 `jpeg_marker_check.sv`，PCLK 域采样有效字节，HREF 结束不当作 JPEG EOI。
保留 HREF/VSYNC 极性参数、异步置复位/同步释放、2 MiB 上限；记录无 SOI/EOI、异常 VSYNC、
空帧、超长和标记错误，错误后下一 SOI 恢复。输出暂属投机字节，下游必须整帧丢弃错误帧。
JPEG 长度段内的 FF D8/FF D9 不作为标记，熵段处理 FF00、restart/fill；不实现 JPEG 解码器。
已有 Icarus/标准库即可复现，无新增运行依赖。1000 帧真实自有 JPEG 激励逐字节通过，
包括 HREF 间隙、EOI 紧邻 VSYNC、正反极性、错误统计、最大长度边界和停 PCLK 复位恢复。
完整用户 JPG 365954 字节也作为输入激励：JPEG 到 EOI 为 365930 字节，尾部 24 字节不进入帧输出；
三帧及紧邻 VSYNC 的额外一帧比对通过。原文件不修改，AES MVP 的完整文件加密记录不变。
这不是实物摄像头采集，未改板上 M02 PL、SD/Flash 或网络；完整 M03/G1 未通过。
有效独立 OOC 综合 `m03_synth_3`：184 LUT/394 FF，无 latch/BRAM/DSP/黑盒，0 综合警告/错误。
综合时序有 HD.CLK_SRC/缺少板级 IO delay 的范围限制，不作为实际采样时序通过；详细口径见 M03 文档。
共享综合脚本的 M02 默认路径也重跑通过，421 LUT/250 FF、2 原生开漏 IOBUF，未改变 M02 RTL。
复现、接口、哈希与独立综合证据见 [M03](../doc/m03.md)；下一步 M04 FIFO/AXIS，再 M05 DMA/DDR。

## M04：原生异步 FIFO 与 AXIS

按 steps 连接 M03 的投机字节输出，不下载板卡或建立临时 BRAM/JTAG 快照。
采用已安装 AMD `xpm_fifo_async`：8-bit BRAM 数据 FIFO + 33-bit/16-entry LUTRAM 帧提交 FIFO。
确认整帧后再交给 AXIS；错误/溢出帧按已存长度清理，不输出半帧，也不复位已提交的好帧。
背压、描述符容量保护、下一 SOI 恢复、32/64-bit TKEEP/TLAST/TUSER、统计原子快照已实现。
默认帧上限 65536 字节，未把协议/M03 的 2 MiB 上限标成片上缓存能力。
此前用户 JPG 的 365930 字节 JPEG 帧超限；实际摄像头最大帧长待 M05 测量后选缓存预算。
两个时钟须在 FIFO 初始化/复位恢复期间运行；M05 要协调 PCLK、M02 配置和 DMA 复位。

实际 XSim/XPM 模型的三个配置（32-bit/1024、64-bit/1024、32-bit/65536）分别通过：
1..17 字节尾包、200 组随机长度/异步频率相位抖动、最大长度/多一字节、旧帧错误与新 SOI
同周期、帧外错误、强制背压 FIFO 溢出、描述符饱和、复位中断与全部统计恢复。
各配置还通过真实自有 685-byte JPEG 的 1000 帧 DVP → M03 → FIFO → AXIS 字节记分板，
以每批 25 帧连续发送验证，含 HREF 间隙与真实截断 JPEG 的 VSYNC 撤销。
1..17 字节等接口激励不当作可解码 JPEG；1000 帧仿真不是实际板卡 FPS/稳定性验收。
扩大至 64 KiB 后首次测试因固定 40000 周期排空预算不足而超时，已按深度修正测试预算；
不是修改/放宽硬件丢帧策略，随后三个配置全部通过。
没有新增 Python 包或复制 IP 源码；hook 新增这一个原生检查，详见 [M04](../doc/m04.md)。
完整 hook 已通过：5 份向量一致性与 M00/M01/图片 MVP/M02/M03/M04 共 25 项离线测试。

有效 OOC 综合 `build/vivado/m04_synth_5`（XC7Z020-2，默认 32-bit/64 KiB）：
523 LUT（499 logic/24 memory）、1374 FF、16 BRAM36（11.43%），0 latch/DSP/黑盒。
综合阶段 0 error/critical warning，58 个 warning 保留，包含未使用 IP 输出、内部裁剪与
原生 FIFO FSM 安全状态提示；不宣称零警告。PCLK 13.888 ns / AXIS 10 ns 的综合估计
WNS 4.818 ns、WHS 0.157 ns、WPWS 4.500 ns。
原生约束覆盖的 CDC：PCLK→AXIS 37、AXIS→PCLK 3 个端点均 Safe，Unsafe/Unknown=0；
报告保留无共同主时钟的结构提示与原生宏上下文 waiver，不是物理亚稳态验证。
先加载 EARLY 的 `prj/m04_ooc.xdc`，再处理 XPM scoped 约束；保留原生 max-delay/bus-skew，
不使用全局异步 clock-group 覆盖这些约束。灰码 bus-skew 需求为真实 10 ns，综合估计满足。
早期 synth_2..4 先综合后创建时钟，导致原生约束采用 1000 ns 占位周期，保留作开发记录，
不作最终 CDC 时序产物；synth_1 命令把其他选项放在 -tclargs 后导致参数数量错误，也不计通过。
DCP SHA-256：`79dbece1a1b78863af624f3981b6ac43cda4ce2e47a810d7615f070b0b813c4f`。
综合有 HD.CLK_SRC/无板级 IO delay 的范围限制，bus-skew 未布线；未改板上 M02、
网络或 SD/Flash，未取得实际摄像头 JPEG，M04/G1 物理验收仍待 M05 集成。
下一步 M05：短包发生器 → DMA/DDR → 缓存/错误恢复 → 实拍保存/解码；M11 网络仍最后接入。

## M05：原生 DMA/DDR 集成

新增两个 AMD AXI DMA Simple Mode，capture S2MM 与 crypto MM2S/S2MM，共享 PS HP0；
crypto 本阶段为传输回环，不冒充 AES-GCM。JPEG 双缓冲、独立输出包、64 KiB 上限、
缓存方向、原生 BSP 中断、有界完成/错误/复位处理、所有权与 UART 转储已编写。
主机只读完成且保持 SENDING 的 ELF-owned DDR 帧，再显式 release，没有 BRAM/JTAG 快照旁路。
已有环境完成 Icarus 4 模式/4000 组路由、C 10000 轮所有权、主机边界校验和实际 M05
原生 XSim/XPM 停 PCLK 复位/背压/PCLK witness 检查；M02/M03/M04 回归通过。
M04 桥读侧改用原生异步置低/AXIS 同步释放复位，其三配置各 1000 帧回归再次通过。

开发产物保留但不当验收：m05_board_1 未同步 PS 配置/flush 到 PCLK，CDC/内部时序失败；
首版 XDC 的 foreach 不属于 read_xdc 支持的语法，已展开管脚、分离 EARLY 时钟与仅实现约束。
m05_board_1/2 被本助手停止，产物/日志未删；m05_board_3 完成内部布线时序 WNS 0.449/WHS 0.036 ns，
但复位同步器前还有 CDC-10 组合逻辑提示，已将请求在源域寄存，重新构建 m05_board_4。
旧 Vitis 构建因为期间 RTL 改动被源码哈希保护拒绝，无有效 manifest，没有下载旧版上板。
实际原生 SDT 把 capture 唯一 S2MM 中断放在 IntrId[0]、[1]=ffff，已按配置修正，
不套用双通道示例的 RX 索引；三个 GIC SPI 编码为 401d/401e/401f，使用原生同一套中断封装。

最终 `m05_board_4` 原生实现 WNS +0.464 ns、WHS +0.043 ns，CDC 无 Critical，
10 ns bus-skew 布线无违例，DRC 无 Error；bitstream SHA-256 为
`bf9feae357dbbf17c182b6c4e2155c60b58ed633b819082720e95ad77026a73c`。
同一版 bit/ELF 在 CF7020B 实测缓存关闭的 32 次变长传输及 2 次预期错误后的恢复，
全部 34 次数据/实际长度检查通过，耗时 49166 us；RX IRQ 34、TX IRQ 35、
错误 IRQ 1、预期超时 1、背压计数 211904，最大长度 65536。
结果见 `data/captures/m05_20260927_231856_679327/result.json`。
次日尝试 10000 次时，在下发邮箱命令前发生 ARM AP transaction timeout；
JTAG 能枚举 xc7z020，但 DAP 报 transaction error，故不是 DMA 压测结果。
重上电后旧配置缓存开关各 10000 次通过；实拍被 PCLK 安全检查挡下：
实测 83.9 MHz，超出当前 72 MHz 时钟约束，状态 43，不产生伪图片。
按 OV5640 `0x3035[7:4]` 系统分频定义，将寄存器表从 0x11 改为 0x21，
重建 `m05_pclk42`，保留安全检查，实测 PCLK 41.963 MHz。
新镜像 bit SHA-256 为 `d9f5d82a955e5423975d553142d8f528a5f2fe6b1616c71a29a387b700b4d452`，
布线 WNS +0.464 ns、WHS +0.043 ns，CDC 无 Critical、bus-skew 无违例。
新镜像缓存关闭/开启各 10000 次不同长度传输，加两次预期故障恢复，全部通过；
耗时分别 8437556/2461060 us，无重新下载 bitstream。
32 帧实拍与 1000 帧连续实拍均通过；1000 帧 133750121 us，总长 6277230 bytes，
平均 6277.23 bytes、最大 6331 bytes、约 7.48 fps，零错误/超时/丢帧/溢出。
末帧 `data/captures/m05_20260928_103346_800362/frame.jpg`（6259 bytes）
已按 320×240 JPEG 完整解码并目视确认，之后显式释放 SENDING 缓冲。
M05 和 G1 列出的功能判据已通过；DVP input_delay 与完整 G0 未验收。M02 的 20 次物理断电/上电后配置和无模组 fail-closed 后续已完成，见 [M02 实板报告](m02_sensor_reset_board_20261011.md)。
复现、接口与容量/IO 验收范围见 [M05](../doc/m05.md)。网络仍最后，不写 SD/Flash。

## G6：开发态 USB 动态会话

2026-09-29，CF7020B 的真实 USB 控制通道完成 ML-KEM-512、双方 Finished、
带 MAC 的 START/REKEY/STOP；PL 用派生会话 Key 对 OV5640 实拍 JPEG 逐包
AES-128-GCM 加密。主机每包认证/重放检查后解码；单会话约 47.3 fps，
双会话换钥 47.244/47.092 fps。坏 Finished 不输出视频，DTR 断开后同次上电
重新握手两段 47.195/47.235 fps。G5 重编回归 234 帧、47.493 fps，篡改拒绝。
代码、复现命令、证据路径和安全限制见 [G6](../doc/g6.md)。
JTAG 注入测试私钥/种子只用于开发；G7 故障测试、实际拔线、
G0 冷启动/LED 和生产级密钥注入/熵源未验收。
后续 G7 长测于 2026-09-29 按用户要求提前停止；日志最后确认约 50 分钟、
141777 帧、47.259 fps，无两小时完成结果。用户例外验收长期运行子项；
未实测满 2 小时，故障子项及 G7 整体仍未通过。

## 2026-10-06 当前工作副本复跑补记

M04/M05 上述原生 XSim/XPM 通过项是先前环境的历史证据。本机 Vivado 2026.1 复跑时，
`xelab` 生成阶段完成，但调用随 Vivado 安装的 MinGW GCC 6.2.0 编译 C 快照失败；
工具本身因 Windows DLL 重定位错误无法启动。当前 Icarus 13.0 复跑的 M01 五项、
M02 四项、M03 两项、M07 一项和 M08 102 向量端到端 AES-GCM 均通过；
M05 帧所有权、AXIS 路由和 DMA 缓冲区三项中两项通过，
其原生集成 XSim 仍未通过。部分 Icarus 编译在退出时返回 Windows 状态 3221225477，
但已生成非空 VVP 文件；新共享助手只对该精确退出码和非空文件继续，并要求 `vvp`
实际运行、匹配原有功能通过标记。该兜底没有放宽 HDL 判据。M04/M05 原生 XSim 本轮仍未通过。
完整命令与调查记录见 [电脑构建记录](pc_build.md)。

## 2026-10-11：开发态可选安全清理配置

新增 `--g6-dev-secure-cleanup`，在保留开发 JTAG/mailbox 和 host-seed 机制的前提下，将有界 USBPS overlay 与 DMA/GCM/frame/TX 有序清理纳入 G6 开发 ELF；默认 profile 不变。manifest 标记为 `development_jtag_mailbox_secure_cleanup`，候选 ELF SHA-256 为 `b9eab1d80cf1a1e4fa15f7ae2afa27a4dad1120e0c5dafd62f589c7b096b1ca6`，`board_validated=false`。清零读回工具现在也覆盖开发测试私钥、seed、mailbox、计数器和 ready 标志，并且仅输出零化状态；定向回归 16 passed、37 subtests，全量 `sim/tb` 166 passed、91 subtests（323.65 秒）。当前仍未做板端 AP0 读回；生产 provider、可信熵源、密钥存储和生产安全状态仍未通过。详见[生产安全实施记录](production_security_profile_20261011.md)。
