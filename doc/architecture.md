# 四端架构与目录契约

当前基线：CF7020B/Zynq-7020、OV5640、Windows PC、Android，可选公网 Linux 中转。
用户已确认 SD 本地身份版可用及首次连接问题修复；本次文档整理未新增实测。

```text
视频：摄像头 → 板端 JPEG/AES-GCM → USB Slave → PC → [公网 TCP 中转] → 手机认证解密
控制：手机 ⇄ [中转] ⇄ PC ⇄ 板端
```

## 职责

| 子项目 | 代码与职责 |
|---|---|
| `board/` | RTL、裸机固件、摄像头/DMA、ML-KEM 解封装、AES-GCM、SD 与 USB Slave |
| `pc/` | Windows CLI、账号、TLS、USB/WSS 密文桥与主动 SSH 反向隧道 |
| `mobile/` | Android 登录、配对、公钥指纹、ML-KEM 封装、认证解密与显示 |
| `server/` | 受限 SSH 公钥接入和透明 TCP 转发，不终止业务 TLS |

共享协议在 `doc/`，测试在 `sim/`，公开标准向量在 `data/kat/`，必要技术证据在 `report/`。
板端使用 Vitis Standalone，不引入 Linux 或 USB 网卡。以太网保留为最后的可选任务。

## 连接与授权

手机经 HTTPS/WSS 连接 PC 服务，公网时通过服务器的 TCP 端口和 PC 主动建立的 SSH 隧道到达 PC 回环监听。
PC 校验用户名/密码，配对 JSON 只包含 WSS 地址、公钥和 SHA256；不带密码或 token。
一个板卡同时只有一个观看者；同账号新设备需明确确认接管，旧端不自动抢回。
旧 USB 清理完成后才交接，迟到的旧连接不能控制新会话。TLS/账号在 PC，服务器只认证 PC 的专用 SSH 公钥。

## 传输与队列

保持 [字节协议](protocol.md)：USB 外层 `channel:u8 || record_length:u16_be || record`。
WebSocket 每条二进制消息承载一条完整 USB 记录，USB 侧处理拆包、粘包、长度与超时。
控制记录最多 1036 字节，视频最多 1456 字节；外层头增加 3 字节。
路由字段不代替内层 MAC/GCM 标签认证，转发器不改 AAD、标签或密文。
当前有界队列按整帧准入或舍弃，控制不丢；非法记录、控制溢出或超时关闭会话。
标准 Ping/Pong 限制网络在途积压，不等于手机已经验证 GCM 或显示视频。
STOP、断连与接管清理旧会话，重新连接必须重新握手，不拼接新旧密文或画面。

## 密钥与信任

SD 保存固定 ML-KEM 身份私钥和双槽秘密随机状态，普通 `eyepqc run` 不读入或注入板端秘密。
身份 bootstrap 建立认证通道，再交换经过 MAC 认证的临时 ML-KEM 公钥/密文，HKDF 派生业务密钥并再次 Finished。
新连接、接管和定时/手动换钥更新临时密钥，固定身份不随每轮换钥改变。详见 [suite2](account_ephemeral_protocol.md)。
手机首次自动配对信任 PC 的 HTTPS 服务，既有指纹变化拒绝自动替换；独立可信指纹核对可缩小首次信任范围。
首次材料配置端仍须可信，知道初始状态者可推算后续确定性状态。无硬件熵、受保护存储或整卡回滚保护。
PC 可见账号凭据和连接元数据；“转发代码不解密”不能扩展成抵御知道初始材料的恶意配置电脑。
状态提交、掉电边界及文件格式见 [SD 身份说明](g6_sd_identity.md)。

## 验收

软件、构建、真机显示、冷启动、故障和长期运行分别记录，旧版结果不自动算新版本通过。
用户统一验收，入口见 [四端部署](deployment/README.md) 和 [实施顺序](steps.md)。
