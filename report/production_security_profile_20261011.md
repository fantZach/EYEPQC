# G6 生产安全 profile 隔离进展

更新：2026-10-11。本次只做源码、构建脚本和电脑端测试；未连接板卡、未改 SD/Flash/eFuse。**生产安全仍未通过。**开发态装载与生产服务接口已隔离，生产候选现已编入受限清理路径；真实熵源、密钥存储、可信启动和板端清零读回仍缺失。

## 本次实现

- 默认开发 profile 保留现有 JTAG 测试 mailbox 与 host-seed/HMAC 随机实现，保持既有开发流程。
- 显式以 `G6_PRODUCTION` 编译时，固件不定义 `g6_sk_load`、`g6_seed_load`、`g6_ready`，也不含静态 `private_key`、`random_seed` 或 host-seed 派生的 `board_random()` 路径。
- 生产 profile 在启动 USB/摄像头前调用外部 `g6_production_security_init()`、熵接口和密钥服务；任一步失败即停机，不开始枚举。HELLO 随机数来自固件内 HMAC_DRBG-SHA-256，熵由 `g6_production_entropy_bytes()` 提供；每 1024 次生成前强制重播种。熵/DRBG 报错时清零输出并拒绝 HELLO_ACK。
- 生产 profile 启动时只在栈上临时读取密钥，用 ML-KEM 检查并固定公钥身份后清除副本。每次 KEM 解封装重新从 provider 读取、验证并比较公钥身份，之后清除栈上的密钥和公钥哈希。密钥服务失败或返回另一设备身份时拒绝解封装。严重协议错误关闭 provider。
- 新增 `--g6-production-provider <source.c>` 构建入口。若未给出该源文件，构建继续生成明确标为 `development_jtag_mailbox` 的开发 profile；显式给出时，manifest 标为 `external_provider_unvalidated` 并记录 provider 源码 SHA-256。外部实现缺失时，生产链接因 provider 符号未定义而失败。

对 CPU 本地密钥清理做了源码边界复核：`production_decapsulate()` 在返回前清除栈上的 ML-KEM 私钥副本与公钥哈希，调用方清除共享密钥；便携式 ML-KEM 的解封装中间缓冲通过 `MLK_FREE` 调用 `mlk_zeroize()` 清理。这是源码与构建配置层面的证据，仍需目标板对 PS/DDR/DMA/PL/GCM 状态做停机、cache 处理和清零读回。

此前构建审计发现 `--g6-production-provider` 未定义 `G6_SECURE_CLEANUP`，且该宏与自动恢复诊断耦合。本轮已拆分 `G6_SECURE_CLEANUP` / `G6_AUTO_RECOVERY`：生产 profile 只开启安全清理，不带自动恢复状态；G6 自动恢复候选仍显式开启两个宏，保留原路径。生产 builder 生成有界 USBPS overlay，将其纳入编译，并记录 SDK 原件、overlay、生成 probe 和 manifest 的 SHA-256。ARM link map 确认使用 overlay 的 endpoint/CH9/interrupt 对象，且未链接 stock endpoint/interrupt 库成员；ELF 含 `g6_secure_cleanup_diag`（120 字节）、`secure_cleanup`、`secure_tx_quiesce`、`secure_tx_wipe`、`secure_tx_rebuild` 与 `usb_cdc_secure_cleanup_tx`。另将安全清理扩展到生产 profile 的 USB 断连退会话路径；清理完成才回到等待新会话，任一阶段失败都会 fail closed。实际生产 profile 的离线链接与 harness 证据不等于板端所有权或清零读回验收。

`src/ps/src/g6_hmac_drbg.c` 实现 [NIST SP 800-90A Rev. 1 §10.1.2](https://csrc.nist.gov/pubs/sp/800/90/a/r1/final) 的 HMAC_DRBG-SHA-256，启动明确请求 256-bit security strength，并按 strength 检查 entropy_input/nonce 最小长度；另限定输入长度、最大请求长度和 1024 次重播种间隔。失败输出会清零，熵/provider 或密码运算失败时清除 DRBG 状态。生产接口启动时取 32 字节 entropy_input 和 16 字节 nonce；重播种时取 32 字节 entropy_input 与 16 字节 additional input。接口定义不是熵评估：provider 必须用实际源证明所需熵量、健康检查和故障锁止。仓库没有实际 provider 源码；任意 provider 也不会自动获得可信、认证或量产状态。

后续代码审阅发现，DRBG API 的参数/熵长度拒绝此前可能留下传入的旧状态，即使当前生产调用者会在失败后额外 uninstantiate。本轮将 fail-closed 约束下沉到 API：非法 instantiate/reseed/generate 输入会覆写 DRBG state；`RESEED_REQUIRED` 保留为正常门禁，状态仍可接受 reseed。新增用例验证先有效实例化、再用不足熵重新实例化/重播种、以及非法 additional-input 长度时旧状态均被清除，同时保留过期 counter 的正常 reseed 行为。该项是 API 层软件清理强化，不替代熵源健康检测或实际 provider。

熵源架构事实已按 AMD 官方资料核实：WP467 说明 Zynq-7000 没有为应用层 session key 生成提供的片上 silicon RNG，但用户可在 PL 实现 RNG；WP468 说明可编程安全逻辑要建立信任，依赖认证启动链，避免未授权 bitstream 替换熵源。项目源码搜索也没有找到 TRNG、PUF 或熵采集 IP/driver。故当前不能实现一个可信的纯 PS entropy provider；下一步必须检查实际 bitstream 和板卡原理图，确认 PL TRNG 或外接熵器件，再做熵评估、健康测试与安全启动绑定。[AMD WP467](https://docs.amd.com/api/khub/documents/~r0Z3L3XXjpo2pmVrIvd_g/content)、[AMD WP468](https://docs.amd.com/api/khub/documents/kpDj1NsgdFh10n3DhSxgdA/content)。这是器件架构边界结论，不是板上熵源存在性的测量结果。

NIST [HMAC_DRBG-SHA-256 示例向量](https://csrc.nist.gov/CSRC/media/Projects/Cryptographic-Standards-and-Guidelines/documents/examples/HMAC_DRBG.pdf)的三种情形共五组 64 字节输出纳入原生 C 回归：无附加输入的两次连续输出；带 personalization 的两轮 Generate，使用两组非空 additional_input；以及显式成功重播种后的输出，并检查重播种计数器由 1 复位、生成后增至 2。这样也覆盖了生产代码把主机 nonce 混入 DRBG 状态的路径。向量只验证确定性算法实现，不证明熵源、CAVP/FIPS 认证或目标板行为。

## 验证

`sim/tb/test_g6_hmac_drbg.py` 编译实际 DRBG、会话 HMAC 与 TinyCrypt SHA-256，NIST 连续输出向量、输入边界、未实例化状态、重播种门禁和擦除检查通过。`sim/tb/test_g6_production_profile.py` 编译并运行实际 `g6_usb.c` 的 `G6_PRODUCTION` 分支。C harness 覆盖：provider/熵启动失败不读取密钥、密钥接口部分写入后整块清零、重播种失败不发送 HELLO_ACK、密钥身份变化时不解封装、匹配身份时每次 KEM 都经 provider 重新取钥。`nm` 确认测试生产二进制没有开发 mailbox 或 `random_seed` 符号。固定模式测试熵不具备真实熵或存储安全属性。

2026-10-11 首版 production profile 用临时 fail-closed provider 完成 XC7Z020 ARM 交叉编译与链接：`build/vitis/g6_prod_profile_final_20261011/g6_usb/build/g6_usb.elf`，SHA-256 `fe3511229c4725abfb214784ea013b03c71dec512fe37eefa598742748e22a7b`；输入 XSA SHA-256 `46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`。manifest 标为 `external_provider_unvalidated`、`board_validated=false`，DRBG 和 G6 源码哈希匹配该次构建源码。ELF 含 DRBG instantiate/generate/reseed 入口；开发 mailbox、host seed、计数器和静态私钥数据符号为零。临时 provider 的初始化、密钥、熵接口全部返回失败；该产物不含可用熵源或密钥服务。

最新安全清理候选使用同一 XSA 和 fail-closed provider：`build/vitis/g6_prod_secure_cleanup_candidate6_20261011/g6_usb/build/g6_usb.elf`，SHA-256 `50baa8ba43fdb1a40d5cb3bf0f138e39a480893d1b6ce5958433c1aae7a7ce52`。输入 XSA SHA-256 为 `46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`，DRBG 源 SHA-256 `838f0dff03ad87e1fc77b21a9b6af79904e538aed552bf7cdbc453a4c5e71717`、provider 契约头文件 SHA-256 `e6df75b0a2f5f46c65dab90585bb8c763feebe65d6946ff06cad4b9355266f62` 与 manifest 匹配。manifest 的 `production_secure_cleanup=bounded_usbps_overlay_and_dma_gcm_frame_tx_callbacks`、`security_profile=external_provider_unvalidated`、`board_validated=false`；编译参数有 `G6_PRODUCTION` 和 `G6_SECURE_CLEANUP`，没有 `G6_AUTO_RECOVERY`。使用 Vitis 配套 `arm-none-eabi-nm` 检查，ELF 含 DRBG instantiate/generate/reseed 与 secure-cleanup 符号，未见开发 mailbox/host-seed 符号；link command 使用候选目录内的有界 USBPS endpoint/interrupt 对象。provider 的初始化、熵和私钥读取均故意返回失败，因此它不可用于启动视频，也不是生产 provider。

## 主机握手临时秘密生命周期（电脑端）

`src/host/m09.py` 现在把 ML-KEM keygen/encaps/decaps 的私钥或共享秘密返回到可覆写的 `bytearray`；原生 C 输出缓冲仍在返回前清零。`src/host/handshake.py` 将 HKDF 中间值和 56 字节派生材料放在可覆写缓冲中，退出 `derive()` 时清 PRK、T1、T2 与上下文；`HostSession.begin()` 在成功、重复 transcript 拒绝或异常退出时清本次拥有的 encapsulation coins、shared secret 与完整派生材料。生产 G6/M10 主机入口在调用后也清传入的 coins 缓冲；离线 board 测试路径清 decaps shared/material 和私钥缓冲。握手会话关闭时，先前持有引用的 video/control key 缓冲会被覆写后再从 session 释放。

验证覆盖：`test_g6` 新增成功握手、关闭及重复 transcript 拒绝后，对 coins/shared/material/key 引用逐字节检查为零；当前针对性结果为 G6 15/15、演示 12/12、M09 NIST KAT/1000 次重复测试通过、M10 KDF/会话互操作通过。该改动只减少应用层可控缓冲的保留时间。Python `hmac.digest`、解释器、分配器和底层密码库仍会产生不可直接覆写的临时副本；因此不宣称 host 全进程清零或抗内存取证，也不改变板端 provider/熵源/密钥存储缺口。

另以同一 XSA 和当前构建脚本编译开发 profile：`build/vitis/g6_dev_profile_final_20261011/g6_usb/build/g6_usb.elf`，SHA-256 `f80f9fd014d0ee6d329b8149c7a12cb62e881801eb10858e722d807f236dff1c`。开发 ELF 保留 mailbox 和旧开发随机状态，未编译/链接 DRBG 源；生产 ELF 则相反。两个 manifest 分别标记 `development_jtag_mailbox` 与 `external_provider_unvalidated`。两个构建的 `g6_usb.c`/DRBG 源码哈希均匹配；该对照验证 DRBG 仅进入显式生产配置。

本节最新全量电脑端回归 `python -m unittest discover -s sim/tb -p 'test_*.py' -v` 为 **128 tests / OK**，耗时 **268.005 秒**。覆盖 host 临时秘密清理、DRBG 输入失败状态覆写、有效重播种和全部既有 RTL/协议用例；最新生产 ARM ELF 重建、宏/符号与 link map 检查通过。电脑端回归不代表熵源、密钥服务、host 全进程清零或板端安全验收。

## 仍未完成

必须由平台设计与板卡验证补齐真实 entropy source、SP 800-90B/90A 相关的源评估与健康/重播种策略、长期私钥生成/封装/持久化/身份绑定/轮换/RMA/销毁、secure boot/JTAG 生命周期、复位与掉电行为、PS/PL/DDR/DMA/USB 全域清理及读回。当前将私钥在解封装期间短暂复制到 PS 栈上；provider 需要明确并验证保护该副本的实际边界。接口隔离只阻止生产 profile 误走开发 mailbox 和主机 seed 路径，不是生产安全认证或 G6 验收。
