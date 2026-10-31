# Windows PC 子项目

负责视频 USB 接入、WSS 账号登录、密文转发和可选 SSH 公网上行隧道。
当前 SD 本地身份版本只需 `eyepqc run`，不读取板端私钥或注入 seed。

[新手部署](DEPLOYMENT.md) · [完整配置/构建](DEPLOYMENT_ADVANCED.md) · [打包说明](RELEASE_README.md)

## 日常使用

```powershell
eyepqc --version
eyepqc check
eyepqc run
```

保持前台窗口打开，按 Ctrl+C 正常退出自有 relay 和隧道。不要重复启动或结束无关进程。
首次安装或更换 USB 接口后，通过 `eyepqc config set serial_port COM7` 设置实际视频端口；编号以设备管理器为准。

```powershell
eyepqc account list
eyepqc account add --username viewer2
eyepqc account passwd --username viewer2
eyepqc account delete --username viewer2 --yes
```

密码在终端隐藏输入，不写入命令参数。账号库使用加盐 scrypt，修改后正常重启服务加载新快照。
同账号新设备须显式确认接管；当前单块板卡同时只有一个观看端，不自动反复抢回。

## 首次配置

安装包不包含真实账号库、证书、SSH 私钥、板端私钥或配对文件。
先按进阶教程准备公开配对信息、PC TLS 材料、账号和可选隧道材料，再 `eyepqc check`。
板端公钥必须与 SD 身份一致，已有手机指纹不能靠重新生成身份绕过。
公开示例使用 `203.0.113.10`、SSH `22022`；部署时替换，证书地址与手机端点保持一致。

## 转发规则

公网路径：手机 WSS → 服务器透明 TCP → PC 主动 SSH 反向隧道 → PC → USB 板卡。
TLS 和账号校验在 PC；手机与板卡执行 suite2 的 ML-KEM/HKDF/Finished 和视频认证。
relay 不导入业务握手或解密模块，验证记录长度/方向后转发原始字节。
USB 记录支持碎片和粘包，网络每条二进制 WebSocket 消息承载一条完整记录。
队列有界，视频按整帧舍弃；控制消息不丢，溢出或非法输入关闭会话。
STOP 后排空旧数据再关闭，接管须等待旧 USB 清理完成，不能交叉控制两会话。

用户已确认此前首次连接问题修复；本次整理未新增实测。软件检查不代替手机显示、帧率或长期运行验收。

## 历史调试与开发

`--dev-usb-bootstrap` 仅适用于旧 USB 初始化固件，不能用于当前 SD 身份模式的恢复。
旧方案中 PC 知道板端私钥和 seed；即使纯转发程序没有解密，也不提供对该 PC 的保密。
源码参考接收端可独占 USB 完成解密实验，不能与正在运行的 relay 同时访问板卡。
测试与工具命令见进阶教程，协议见 [账号/临时 KEM](../doc/account_ephemeral_protocol.md)。

[安全说明](../SECURITY.md) · [第三方许可](THIRD_PARTY_NOTICES.md)
