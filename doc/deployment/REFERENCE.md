# 进阶部署索引

日常安装使用 [新手入口](README.md)。需要自己构建、配置证书或维护服务器时，再查对应高级教程：

| 部分 | 进阶教程 |
|---|---|
| 开发板 | [SD 身份、固件构建和历史调试兼容](../../board/DEPLOYMENT_ADVANCED.md) |
| Windows PC | [安装、账号、TLS、SSH 和配置](../../pc/DEPLOYMENT_ADVANCED.md) |
| Android | [构建、公开 CA 信任和正式签名](../../mobile/DEPLOYMENT_ADVANCED.md) |
| Server | [受限 SSH 部署、维护与回滚](../../server/DEPLOYMENT_ADVANCED.md) |

当前使用 SD 本地身份和普通 `eyepqc run`。旧 USB 注入模式只用于明确选择的历史固件。
示例 `203.0.113.10` 与 SSH `22022` 不是实际服务；替换为管理员提供的地址和端口，并同步手机地址、证书 SAN 与 SSH 主机信任。

## 哪些材料可以传给谁

| 材料 | 保存位置/用途 |
|---|---|
| 板端私钥和两个随机状态文件 | SD；首次准备环境可信，不公开、不克隆或恢复旧状态 |
| 板端公钥、指纹、公开 pairing JSON | PC，登录后给手机 |
| PC 账号库、TLS/SSH 私钥 | PC 受保护目录，不进入安装包或服务器 |
| TLS 证书链 | PC 对手机提供，地址和有效期必须匹配 |
| CA 公开证书 | 按部署需要显式打包 APK，默认源码只信系统 CA |
| CA 签发私钥、Android 签名 keystore | 部署者受保护配置环境，不随程序分发 |
| SSH 公钥与服务器 host 公钥 | 各自独立核验，不把一次 keyscan 当作信任证明 |

板卡身份、TLS/CA 和 SSH 主机三类指纹用途不同，不能互相替代。私有材料只做受控备份，不回传聊天。
验收范围见 [统一验收表](ACCEPTANCE.md)；当前用户确认见 [正式版记录](../releases/first-stable.md)。
