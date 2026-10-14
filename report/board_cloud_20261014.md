# Board 公网透明中转兼容审查（2026-10-14）

结论：冻结的 OpenSSH 透明 TCP 中转方案无需修改板端密码实现、协议字节或 USB 接口。
本轮仅补 `board/README.md` 的四端接口说明和此报告；没有复制协议、新增网络栈、依赖或固件构建。
主聊天最后统一暂存/提交；本聊天未操作共享 Git index。

## 审查依据与条件

已完整读取 `doc/cloud_relay_plan.md`、suite2 契约，核对当前 `protocol.c/.h`、`g6_usb.c`、USB 控制收包边界及相关测试。
仓库/board 与工作区祖先目录没有发现适用的 `AGENTS.md`；按 Ponytail 保留现有最小实现。

Board ⇄ USB ⇄ PC WSS（回环监听）⇄ SSH 反向 TCP ⇄ Android。
云端不改变 PC⇄Android WebSocket 消息，也不终止业务 KEM/AES；TLS 实际终止于 PC，
账号、接管/owner fencing、完整记录校验、背压和清理仍由 PC 管理。
**兼容结论以隧道保留 TCP 字节顺序、PC 转发完整 USB 记录为条件，是源码接口审查，不是公网实测。**

| 消息/载荷 | 完整控制或视频记录字节数 | 加 3 字节 USB 外层后 |
|---|---:|---:|
| HELLO / ACK | 48 | 51 |
| 身份 KEM ciphertext | 780 | 783 |
| 任一 bootstrap/business Finished | 44 | 47 |
| 临时 KEM offer / reply | 876 / 844 | 879 / 847 |
| START / STOP / REKEY | 52 | 55 |
| 最大视频分片：header40 + payload1400 + tag16 | 1456 | 1459 |

控制外层仍为 `EYPQ/version/type/reserved/body_length_BE32`，控制 body 最大 1024B，
完整控制记录最多 1036B；USB 外层仍 channel1 + BE16 长度，视频为 channel2。
`send_control` 与 USB 控制接收器保持 12..1036B 校验；完整视频分片仍小于 1472B TX 缓冲。
这些固定界限不因 SSH/TCP 分片、合包或公网 MTU 改变；不会额外扫描损坏字节流进行猜测重同步。

suite2 继续要求身份 bootstrap 的双向 Finished → 认证临时 offer/reply → 业务双向 Finished → START；
业务 key 仅来自临时 KEM，MAC、transcript、会话号、nonce、方向/状态与重放检查不变。
STOP/REKEY 认证后清旧业务状态，下一次 HELLO 重新执行完整 KEM，不把旧 AES REKEY 当临时 KEM 轮换。
握手仍有 15 秒期限，业务 key 仍在 START 后 1800 秒硬截止；客户端 1785 秒提前重建。
公网延迟、吞吐或 PC 队列溢出可能触发现有停流/失败规则；此审查不承诺公网 40 fps、超时恢复或可用性。

## 本轮实际执行的离线回归

| 命令 | 本轮结果及覆盖 |
|---|---|
| `python -m unittest discover -s board/prj/tests -p 'test_ephemeral*.py' -v` | 5 passed：真实 portable C 临时 KEM/MAC/HKDF、二次 Finished/START、篡改/方向/长度/重放、真实 G6 源码 SDK mock 的提前 START/超时/断线清零、生产拒降级/熵失败 |
| `python -m unittest sim.tb.test_g6_cleanup_paths sim.tb.test_g6_production_profile -v` | 2 passed：默认/secure cleanup/恢复候选、debug/优化生产 provider mock；不证明真实 USB/熵源 |
| `python sim/tb/test_g6.py -v` | 16 passed：fragmented/coalesced 内存 USB、身份握手、篡改/重放无图、旧视频 REKEY 排空、20 次认证重建及其他接收边界；合成 JPEG/software GCM，旧 profile 回归 |
| 原 hook 的 `test_m00.py` | 10 passed：标准 KAT、C/Python 控制/视频、长度和认证负测 |
| 原 hook 的 `test_m10.py` | PASS：SHA/HMAC/KDF、Finished、command/replay、rekey/zeroize |
| 原 hook 的 `test_m12.py` | 2 passed：JPEG roundtrip/rejections、USB record 边界 |
| 原 hook 的 `test_g5.py` | 1 passed：packet authentication |

全部使用工作区 `.venv/Scripts/python.exe`。原 `.githooks/pre-commit` 四项未改，
本轮手动运行相同四项测试；最终 commit hook 由主协调执行。
首次以 `-m unittest sim.tb.test_g6` 运行时因该旧测试按脚本目录导入 `test_m10` 而 ImportError；
使用文件既有入口 `python sim/tb/test_g6.py -v` 后 16 项通过。未修改共享测试来掩盖入口错误。

没有运行公网服务器、SSH、PC relay、代理或真实 WSS 服务；没有执行 JTAG、串口、SD/Flash、摄像头操作，
没有读取实板身份私钥或开发 seed 文件。C KEM 回归仅使用公开 KAT 与合成测试材料。
本轮没有做新 ARM 构建、下载/加载固件、手机运行或实际网络测量。

## 历史结果与当前限制

- 历史 suite2 ARM/software 验证见 `board_account_ephemeral_20261014.md`；不是本轮重新构建/上板结果。
- 历史 G0 SD 自检按用户十分钟例外和 PS_RST 窗完成，原三十分钟覆盖未实测；
  以现有 `progress.md` 与 `board_sd_deployment_20261013.md` 的实际范围为准，不能据旧记忆扩大门禁。
- G6 认证视频的 SD 自主身份/熵源装载仍未闭环。当前开发态 PC/JTAG 能接触身份和 seed，
  临时 KEM 不能宣称对恶意 PC 具有前向保密；可信 production entropy/provider、长期私钥安全保存及 secure boot/JTAG 防护仍待落实。
- 云端 SSH 授权不等于手机账号认证，更不替代板卡固定身份 pin/业务认证。
  TLS 叶证书 SAN 须匹配手机使用的云端地址，隧道 host key 与真实云端权限需在部署阶段核验。
- M18/G9 尚未实测；新增公网 G9 不替代既有 G0/G7/G8 或手机验收。
  保留既有 QueueFull/P2P 失败证据，不将本次离线 PASS 写成其修复。
