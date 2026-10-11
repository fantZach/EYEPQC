# G6 生产安全 profile 隔离进展

更新：2026-10-11。本次只做源码、构建脚本和电脑端测试；未连接板卡、未改 SD/Flash/eFuse。**生产安全仍未通过。**本实现将开发态装载与生产服务接口分开，尚未提供或验证目标板的熵源、密钥存储或可信启动实现。

## 本次实现

- 默认开发 profile 保留现有 JTAG 测试 mailbox 与 host-seed/HMAC 随机实现，保持既有开发流程。
- 显式以 `G6_PRODUCTION` 编译时，固件不定义 `g6_sk_load`、`g6_seed_load`、`g6_ready`，也不含静态 `private_key`、`random_seed` 或 host-seed 派生的 `board_random()` 路径。
- 生产 profile 在启动 USB/摄像头前调用外部 `g6_production_security_init()`、熵接口和密钥服务；任一步失败即停机，不开始枚举。HELLO 随机数来自固件内 HMAC_DRBG-SHA-256，熵由 `g6_production_entropy_bytes()` 提供；每 1024 次生成前强制重播种。熵/DRBG 报错时清零输出并拒绝 HELLO_ACK。
- 生产 profile 启动时只在栈上临时读取密钥，用 ML-KEM 检查并固定公钥身份后清除副本。每次 KEM 解封装重新从 provider 读取、验证并比较公钥身份，之后清除栈上的密钥和公钥哈希。密钥服务失败或返回另一设备身份时拒绝解封装。严重协议错误关闭 provider。
- 新增 `--g6-production-provider <source.c>` 构建入口。若未给出该源文件，构建继续生成明确标为 `development_jtag_mailbox` 的开发 profile；显式给出时，manifest 标为 `external_provider_unvalidated` 并记录 provider 源码 SHA-256。外部实现缺失时，生产链接因 provider 符号未定义而失败。

`src/ps/src/g6_hmac_drbg.c` 实现 [NIST SP 800-90A Rev. 1 §10.1.2](https://csrc.nist.gov/pubs/sp/800/90/a/r1/final) 的 HMAC_DRBG-SHA-256，启动明确请求 256-bit security strength，并按 strength 检查 entropy_input/nonce 最小长度；另限定输入长度、最大请求长度和 1024 次重播种间隔。失败输出会清零，熵/provider 或密码运算失败时清除 DRBG 状态。生产接口启动时取 32 字节 entropy_input 和 16 字节 nonce；重播种时取 32 字节 entropy_input 与 16 字节 additional input。接口定义不是熵评估：provider 必须用实际源证明所需熵量、健康检查和故障锁止。仓库没有实际 provider 源码；任意 provider 也不会自动获得可信、认证或量产状态。

NIST [HMAC_DRBG-SHA-256 示例向量](https://csrc.nist.gov/CSRC/media/Projects/Cryptographic-Standards-and-Guidelines/documents/examples/HMAC_DRBG.pdf)中的连续两组 64 字节输出纳入原生 C 回归，用于核对实例化、Generate 与状态更新。该向量只验证确定性算法实现，不证明熵源、CAVP/FIPS 认证或目标板行为。

## 验证

`sim/tb/test_g6_hmac_drbg.py` 编译实际 DRBG、会话 HMAC 与 TinyCrypt SHA-256，NIST 连续输出向量、输入边界、未实例化状态、重播种门禁和擦除检查通过。`sim/tb/test_g6_production_profile.py` 编译并运行实际 `g6_usb.c` 的 `G6_PRODUCTION` 分支。C harness 覆盖：provider/熵启动失败不读取密钥、密钥接口部分写入后整块清零、重播种失败不发送 HELLO_ACK、密钥身份变化时不解封装、匹配身份时每次 KEM 都经 provider 重新取钥。`nm` 确认测试生产二进制没有开发 mailbox 或 `random_seed` 符号。固定模式测试熵不具备真实熵或存储安全属性。

2026-10-11 最终版用临时 fail-closed provider 完成 XC7Z020 ARM 交叉编译与链接：`build/vitis/g6_production_drbg_smoke4_20261011/g6_usb/build/g6_usb.elf`，SHA-256 `511e55ec2f7c5246f61f7e65ab1901a2a58a6eddf8e7ee74056b5b1393a85c73`；输入 XSA SHA-256 `46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`。manifest 标为 `external_provider_unvalidated`、`board_validated=false`，`g6_usb.c` 和 DRBG 源码哈希均匹配当前工作树。ELF 含 DRBG instantiate/generate/reseed 入口；精确符号检查确认开发 mailbox、host seed、计数器和静态私钥数据符号为零。临时 provider 的初始化、密钥、熵接口全部返回失败；此产物只证明最终源码可交叉编译/链接，不含可用熵源或密钥服务。

最终代码全量电脑端回归 `python -m unittest discover -s sim/tb -p 'test_*.py' -v` 为 **127 tests / OK**，耗时 271.962 秒；包含 M04/M05 XSim 与 DRBG/生产 profile harness。强度参数、熵/nonce 最小输入、熵/重播种失败 fail-closed 和两组 NIST 输出向量均在这批回归中。随后报告与 review-bundle policy 更新的定向 8 项测试通过，`py_compile`、`git diff --check` 通过。

## 仍未完成

必须由平台设计与板卡验证补齐真实 entropy source、SP 800-90B/90A 相关的源评估与健康/重播种策略、长期私钥生成/封装/持久化/身份绑定/轮换/RMA/销毁、secure boot/JTAG 生命周期、复位与掉电行为、PS/PL/DDR/DMA/USB 全域清理及读回。当前将私钥在解封装期间短暂复制到 PS 栈上；provider 需要明确并验证保护该副本的实际边界。接口隔离只阻止生产 profile 误走开发 mailbox 和主机 seed 路径，不是生产安全认证或 G6 验收。
