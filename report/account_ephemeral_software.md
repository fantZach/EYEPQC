# 账号与临时 ML-KEM：本轮软件联测

实施依据 [独立方案](../doc/account_ephemeral_plan.md) 与 [冻结协议](../doc/account_ephemeral_protocol.md)。
用户明确本轮只做软件验证，不部署 CA、实际账号/服务或实板固件。

## 已实现

- PC WSS Basic 账号认证、固定强度 scrypt、前置限速/有界后台校验；401/409/503/429 和显式接管。
  旧 owner 先失去控制权限，旧 USB cleanup 完成后才交接；失败 fail-closed。仍单观看端。
- Android schema2 四项 JSON、用户名密码 UI、409 接管确认、4409 提示、不自动抢回、TLS 默认信任/主机名校验。
- suite2 身份 bootstrap → 认证临时公钥 → 临时 KEM → 业务 HKDF → 再次 Finished → START。
  bootstrap videoKey 清零、临时 SK/coins/shared 清理；新配置不能降级 suite1。
- 手机提前 15 秒（1785 秒）发起完整换钥；板端/手机业务会话 1800 秒硬截止，握手期限 15 秒。
  停止/失败/关闭取消 timer，超期停流；旧图像不跨会话显示。

## 协调者实测（软件）

`sim/tb/test_account_three_end.py` 使用实际 C session/ephemeral/ML-KEM 代码生成、解封装、派生与 Finished；
摄像头 JPEG/CDC 为模拟。真实 Python WSS 服务与 Java/OkHttp 客户端使用临时测试 CA/truststore验证 TLS，
没有 trust-all，测试账号/私钥仅是合成 fixture，不使用实板私钥或真实登录凭据。

五窗口全部通过：新连接、手动 REKEY、自动 timer、认证 STOP、STOP 后新连接。
每次客户端控制前缀为 `[1,3,5,11,5,6]`，换钥窗口取得不同临时公钥。
真实 C 中 bootstrap 视频密钥为零，完成临时解封装后 2509 字节临时状态全零。
自动 timer 使用 100ms 的测试注入执行生产同一路径；退出后验证 timer 已取消、无残余 rotation 线程。
最终候选协调者再次运行 13.023 秒；前一轮为13.666秒，Mobile聊天另独立复核13.424秒。

CLI normal/rekey/timer 主动 cancel 退出，桥记录 WebSocket1006/1011；这是本测试退出语义，
不写成优雅关闭或实网断连通过。STOP 窗口为 code1000、drain=quiet。全部窗口 USB 模拟实例关闭并释放 owner。

其他协调者检查：

- 最终 PC tests + Board portable/firmware tests：40 passed、23 subtests（32.80秒）。
  额外锁定服务协议日志级别，防上层 DEBUG 设置导致 Basic 认证头被协议日志输出；小测试已通过。
- 生产 profile、default/secure/recovery cleanup、旧三端 baseline、auto-recovery：12 passed、15 subtests。
- M00 与 M10 单独通过；提交仍仅运行原 M00/M10/M12/G5 hook，不把全部检查塞入 hook。
- 最终 ARM 构建 `build/vitis/g6_account_ephemeral_20261014_2` 完整预检通过：75 文件哈希、672 generated inputs、
  实际 BSP lookup 与 Zynq startup；`board_accessed=false`、`board_validated=false`。
  初始 `_1` 曾在当时源码通过；builder 增加清单字段后其追溯过期，因此不以旧结果冒充最终候选。

旧 cleanup harness 同名 identity ML-KEM stub 与新增真实临时 KEM 符号冲突已修正：只重命名旧身份 mock，
临时模块仍链接真实 KEM。生产 harness 改为 suite2，并继续禁止开发 mailbox/身份私钥导出；
不再误禁临时 KEM 所需 decapsulation 符号，同时新增临时 SK 状态在 FAULT 清零断言。
这是边界更新，不是允许生产应用读取长期身份私钥。

Mobile：core160、JSON39、ephemeral37、公开 C fixture47；APK0.5/code5构建/原签名验签通过。
APK `mobile/app/build/outputs/apk/debug/app-debug.apk` 为4,772,490字节，SHA256
`66a6c687325bbba583143f682f0f9e51057e868946fbc678d9a1990cc929c228`；未安装到手机或公开复制。
独立报告：[PC](pc_account_20261014.md)、[Mobile](mobile_account_ephemeral_20261014.md)、
[Board](board_account_ephemeral_20261014.md)。各端提交分别为 `e30d2c8`、`5067736`、`782e2bd`。

## 未验证 / 风险

没有 29分45秒/30分钟的真实手机持续计时验收；定向边界测试不能代替真实运行。
没有新 profile 实板、手机账号 UI、双手机接管或帧率测量，不能沿用旧40fps反馈作为新实现验收。
未部署真实 TLS CA/账号；自签证书不能直接在 Android 上使用，默认信任未关闭。
当前 SD 仍为 G0；完整 G6 视频 SD 自启动、可信板端熵源和长期身份私钥安全持久化未完成。
开发种子可被可信 PC 重现时，不能声称对 PC 的前向保密；生产 provider 缺失仍须拒绝运行。
