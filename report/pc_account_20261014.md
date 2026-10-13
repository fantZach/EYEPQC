# PC 账号与临时KEM转发实现

2026-10-14。仅PC源码/测试/说明，实际服务、COM口、SD、JTAG均未操作。

实现WSS-only账号模式与显式Bearer开发兼容；账号文件为标准库scrypt加盐哈希，
固定N=131072/r8/p1/maxmem256MiB，交互getpass创建且拒绝覆盖，不输出凭据。
前置全局5burst/1每秒限速、单并发后台哈希、未知账号dummy hash；取消验证仍等后台线程结束才释放配额。

账号401、同账号409确认、不同账号503、限速429。显式takeover=1再次认证后撤销旧owner写权限，
4409关闭旧端，等待旧read/USB清理结束；handoff锁串行处理并发接管。
旧finally只能释放自己的owner；reset/close失败、等待超时及STOP排空超限封锁后续接入。
错误密码不会关闭旧连接。清理失败需人工检查后重启，无自动硬件恢复。

新增schema2导出仅四项公开配置，强制wss，无密码/token；v1显式token-file兼容。
validator支持suite2、type10body864与type11body832；桥控制方向限制10仅板向手机、11仅手机向板。
PC不处理bootstrap/临时KEM/MAC，不解密视频。

验证：pc/tests下34项，真实本机TLS（临时自签测试CA、正常证书验证）+模拟CDC。
覆盖Unicode Basic正确/错误、Bearer不能绕过、409/503、显式4409接管、并发接管、旧read等待、
迟到控制fencing、USB close失败封锁、单哈希忙/全局限速、loop在等待哈希时继续服务、
未知账号dummy hash、生产scrypt参数、拒绝无TLS/不信任证书、schema2/type10/11/mock通路，及原Windows串口回归。
测试证书/账号只在临时目录，本地日志tmp/pc-account-tests.log由Git忽略。
原四项提交hook保留，跨端集成fixture与C/Android测试由协调者负责。

部署命令见pc/README.md。自签TLS须可信CA导入并在Android启用所选CA信任，同时匹配SAN；
不关闭证书验证。Windows账号/证书私钥目录须限制ACL。限速为单进程全局方案，多进程需升级，
短时登录流量可能挤占登录配额，不宣称抗分布式攻击。

未启动实际账号服务、未创建实际账号或证书、未做手机/实板临时KEM/SD验收。
