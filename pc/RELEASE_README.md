# EYEPQC PC 1.3.2 — 项目 v1.0.0 开发态 MVP

本包仅适用于 Windows x64，包含独立命令行 EXE、当前用户安装器及完整第三方说明/许可。
两份 EXE 均未代码签名；未证明所有杀毒产品会放行。不要关闭安全软件或绕过告警。

## 使用前

1. 安装 Windows OpenSSH Client，确认 `ssh` 可用。
2. 由项目操作者准备匹配的六份可信运行材料：账号库、公开 schema2 配对、TLS 证书链、
   TLS 私钥、专用 SSH 私钥、已核验的 SSH known_hosts。本包不包含这些材料、默认密码或可直接登录的身份。
3. 先在手机停止观看，再对旧 PC 服务 Ctrl+C；不要重复运行或盲目结束进程。
4. 运行 `EYEPQC-Setup-1.3.2.exe`，从既有设置或可信旧配置导入材料。没有完整材料时安装器明确拒绝安装。
   不要为了安装而复制他人的私钥或放宽 ACL。
5. 关闭并重开 PowerShell/Windows Terminal，使用户 PATH 更新生效。安装不启动服务；卸载保留 data/settings。

```powershell
eyepqc --version
eyepqc config show
eyepqc check
eyepqc account list
eyepqc account passwd --username viewer
```

账号命令交互输入新密码，不把密码放进命令行；修改仅在服务正常重启后生效。
可以用 `account add --username <名称>` 或 `account delete --username <名称> --yes` 维护账号。
卸载不会删除账号、证书或私钥，应自行妥善备份受保护的用户数据。

## 启动

正常已配置板卡使用 `eyepqc run`。开发态 SD 候选固件另需显式指定视频 USB COM 口及独立准备、
符合当前用户/SYSTEM ACL 的 1632 字节 ML-KEM-512 测试私钥文件：

```powershell
eyepqc config set serial_port COM7
eyepqc run --dev-usb-bootstrap --dev-identity-file "$env:LOCALAPPDATA/EYEPQC/pc/data/private/board-test-identity.bin"
```

`COM7` 仅为示例，实际应使用视频 USB CDC 端口，而非调试串口。
开发身份不在本包或 SD 中，也不由安装器生成。PC 在开发初始化中知道板端私钥和随机 seed；
这不是生产安全、不信任 PC 的端到端安全，亦非不依赖 PC 的独立视频冷启动。
当前 SD 实板仍存在首次查询失败、第二次成功；最新板端 `_6` 改动尚未写卡/实板验收。
本包不自动重试、重刷、复位或抢占 USB，不应宣称已修复首次连接问题。

手机使用账号 WSS 登录并自动下载公开 schema2；不发布明文密码、token 或私钥。
服务器仅透明中转，TLS/账号仍在 PC 校验。切换云地址时必须同时匹配 TLS SAN、手机 endpoint、SSH host key。
先保存故障日志，不以关闭 TLS/地址校验、明文 WS 或反复注入密钥替代诊断。

完整文档：[PC 子项目](https://github.com/fantZach/EYEPQC/blob/v1.0.0/pc/README.md)，
[SD 安全边界](https://github.com/fantZach/EYEPQC/blob/v1.0.0/doc/g6_sd_usb_bootstrap.md)。
项目代码授权未新增；第三方组件沿用各自许可，见 `THIRD_PARTY_NOTICES.md` 与 `licenses/`。
