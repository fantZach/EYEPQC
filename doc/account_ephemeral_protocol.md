# Suite 2：身份 bootstrap 与临时 ML-KEM

2026-10-13 冻结实现契约。代码实现和测试结果必须另记；不据此宣称生产安全或实板通过。
Suite 1 保留为显式开发兼容，账号/schema2 客户端必须请求 suite 2，拒绝 ACK 降级。

## 基础记录

仍使用 USB channel 1，控制头 12 字节：`EYPQ | version=1 | type | reserved=0 | body_length_BE32`。
控制 body 不超过 1024 字节。HELLO/ACK body36 为 `min=1 | max=1 | suite_BE16=2 | random32`。
固定身份 ML-KEM、原 transcript/HKDF、type4/5 双向 Finished 先建立认证 bootstrap。
bootstrap 不允许发送业务视频或接受业务 START；只有完成临时 KEM 和新 Finished 后才能 START。

## 临时公钥与密文

| 记录 | body | body 长度 / 完整长度 |
|---|---|---|
| type10，板端 offer | bootstrapTH32 + temporaryPK800 + MAC32 | 864 / 876 |
| type11，手机 reply | bootstrapTH32 + KEMciphertext768 + MAC32 | 832 / 844 |

- offerMAC = HMAC-SHA256(bootstrapControlKey, ASCII `EYEPQC eph offer v1` + bootstrapTH32 + offer 前844字节)。
- replyMAC = HMAC-SHA256(bootstrapControlKey, ASCII `EYEPQC eph reply v1` + bootstrapTH32 + 完整offer876字节 + reply前812字节)。
- businessTH = SHA256(ASCII `EYEPQC eph business v1` + bootstrapTH32 + 完整offer + 完整reply)。
- IKM 仅为临时 ML-KEM 的 shared32；业务 HKDF 复用 `eye_hkdf56(shared, businessTH)`，info=`EYEPQC v1 keys`。
- 56 字节输出依次为 videoKey16、controlKey32、noncePrefix_BE32、sessionID_BE32。
- 清零 bootstrap keys、临时 SK/coins/shared，重置计数器并进入 CONFIRM；使用 businessTH 重做 type4/5 Finished。
- Finished 标签仍为 `board finished` / `host finished`，新控制 key 验证成功后才接收 type6 START。

## 状态与失败处理

每个新连接/接管执行完整 bootstrap + 临时 KEM；旧 REKEY 仅结束旧会话，下一次 HELLO 必须再次建立临时密钥。
板端业务会话在 1800 秒硬截止；客户端提前 15 秒（1785 秒）发起完整换钥，避免计时起点/网络延迟竞态。
握手阶段 15 秒期限；客户端后台延迟导致超期时停流并重新连接，不能恢复旧密钥。
重复 offer/reply、错长度/TH/MAC、错方向/阶段、降级均拒绝并清零停流。
旧图像/密文只能按既有 REKEY 排空规则丢弃，不能进入新业务密钥或跨会话显示。
生产 keygen 的 coins64 必须来自可信 provider entropy_bytes，失败不退回开发 seed；开发 seed 仅用于功能验证。
身份 bootstrap 认证不是 ML-KEM 签名；本契约不解决熵源、长期私钥保存、持久种子副本或持续板端入侵。

## PC / Android 登录契约

schema2 JSON 四项：`version=2`、`endpoint`（wss）、`public_key_hex`、`public_key_sha256`；不含 token/密码。
每次 WSS upgrade 发送 HTTP Basic（UTF-8 `username:password` Base64），只在 TLS 内传输且不进入日志/URL。
同账号已有 owner 时无确认返回 HTTP409；用户显式确认后连接 `/stream?takeover=1`。
旧连接接管关闭码4409；旧端不自动抢回。PC 在旧 USB cleanup 确认完成后才交接，失败拒绝新 viewer。
账号认证先于任何接管动作；迟到旧消息/清理不能控制或释放新 owner。不同账号仍为单观看端，不自动抢占。
