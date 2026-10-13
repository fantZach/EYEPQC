# 账号与临时 KEM：上板前准备

本轮只准备证书、账号、配对文件与调试 APK，不下载固件、不写 SD、不启动实际视频服务。

后续更新：2026-10-14 用户确认准备就绪后已临时下载固件并完成账号视频实机短测，
手机报告约45fps及手动换钥后恢复；以下保留为准备阶段记录，当前结果见
[实机短测](../report/account_ephemeral_board_20261014.md)。未更新 SD。

## 接线与固件

上板时保留 OV5640、JTAG、USB Slave 和 COM4 调试串口，启动拨码保持现状，按协调者提示操作。
SD 仍是 G0 自检，本次视频测试使用临时 JTAG 装载 `g6_account_ephemeral_20261014_2`。
业务临时 KEM/profile 的软件联测通过不等于此固件已上板或手机已验收。

## 本地测试 TLS

- PC 物理以太网 IPv4 已核对为 `10.179.236.247`，不是 Mihomo/TUN 的 `198.18.0.1`。
- 专用 CA 和服务端私钥只保存在 ignored 本机目录，Windows ACL 限制当前用户与 SYSTEM。
- 服务端证书 SAN 包含实际 IP，并包含 localhost/127.0.0.1 供本机验证，证书用途与有效期必须检查。
- CA 公共证书仅加入 `mobile/app/src/debug/`；debug Manifest / debug-overrides 引用它，release 不含测试信任。
- TLS 的证书链、有效期、主机名检查和 ML-KEM 身份 pin 不关闭；debug CA 不表示业务身份认证已替代。
- IP 变化后重新签发叶证书并更新 endpoint；保持同一 CA 时不需要因 IP 变化重新打包 APK。

## 账号与配置

测试用户名为 viewer，随机强密码仅写本机私有 login.txt，不发到聊天/公共下载目录，也不进入 APK/JSON。
服务器仅保存 scrypt 密码哈希；schema2 JSON 四项为 version=2、wss endpoint、板卡公开 key 与 SHA256 pin。
公开身份沿用现有开发板身份，准备文件不读取板卡私钥、不生成新身份、不 JTAG provisioning。

最终文件路径、公开证书指纹、APK 摘要、实际准备状态由本轮准备报告记录。
材料已准备完成，详见 [最终移交与验证记录](../report/preboard_ready_20261014.md)。
用户需覆盖安装新版调试 APK、导入 schema2 JSON，在手机输入本机私有文件中的凭据。
密码文件只能本机读取；不可公开共享包含 private 的父目录。

## 后续测试顺序

先核对最终构建 → 授权临时装载 → 枚举视频 CDC → 启动账号 WSS → 手机登录/临时 KEM/视频 → STOP/重连/换钥。
另用第二设备验证同账号409确认接管、旧端4409不抢回、错密码不能踢人。旧40fps反馈不迁移为新profile结果。
本阶段仍是开发测试；可信熵源、长期身份私钥安全持久化和完整视频 SD 自启动不由测试 CA 解决。
