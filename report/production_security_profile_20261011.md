# G6 生产安全 profile 隔离进展

更新：2026-10-11。本次只做源码、构建脚本和电脑端测试；未连接板卡、未改 SD/Flash/eFuse。**生产安全仍未通过。**开发态装载与生产服务接口已隔离，生产候选现已编入受限清理路径；真实熵源、密钥存储、可信启动和板端清零读回仍缺失。

## 本次实现

- 默认开发 profile 保留现有 JTAG 测试 mailbox 与 host-seed/HMAC 随机实现，保持既有开发流程。
- 显式以 `G6_PRODUCTION` 编译时，固件不定义 `g6_sk_load`、`g6_seed_load`、`g6_ready`，也不含静态 `private_key`、`random_seed` 或 host-seed 派生的 `board_random()` 路径。
- 生产 profile 在启动 USB/摄像头前调用外部 `g6_production_security_init()`、熵接口和密钥服务；任一步失败即停机，不开始枚举。HELLO 随机数来自固件内 HMAC_DRBG-SHA-256，熵由 `g6_production_entropy_bytes()` 提供；每 1024 次生成前强制重播种。熵/DRBG 报错时清零输出并拒绝 HELLO_ACK。
- 生产 profile 启动时只从 provider 读取公开 ML-KEM 公钥并固定其哈希；长期私钥不通过应用接口导出。KEM 到达时，固件把已固定的公钥哈希交给 provider，由 provider 在不返回私钥的边界内核对密钥身份并完成解封装；固件对返回的共享秘密在任何 provider 错误后都覆写。严重协议错误关闭 provider。
- 新增 `--g6-production-provider <source.c>` 构建入口。若未给出该源文件，构建继续生成明确标为 `development_jtag_mailbox` 的开发 profile；显式给出时，manifest 标为 `external_provider_unvalidated` 并记录 provider 源码 SHA-256。外部实现缺失时，生产链接因 provider 符号未定义而失败。

对 CPU 本地秘密清理做了源码边界复核：生产应用不再将 ML-KEM 私钥读入普通 G6 栈，也不在应用映像中执行解封装；provider 只返回短期共享秘密，G6 在 HKDF/session 派生后覆写它。provider 契约要求私钥留在可信 key service 内，且需对“检查固定公钥身份—解封装”提供不可被轮换打断的操作。共享秘密、后续会话密钥及 host 临时缓冲仍在应用内存，擦除只是缩短驻留时间。这项接口变化不证明 provider 真实实现或硬件隔离；仍需目标板对 PS/DDR/DMA/PL/GCM 状态做停机、cache 处理和清零读回。

此前构建审计发现 `--g6-production-provider` 未定义 `G6_SECURE_CLEANUP`，且该宏与自动恢复诊断耦合。本轮已拆分 `G6_SECURE_CLEANUP` / `G6_AUTO_RECOVERY`：生产 profile 只开启安全清理，不带自动恢复状态；G6 自动恢复候选仍显式开启两个宏，保留原路径。生产 builder 生成有界 USBPS overlay，将其纳入编译，并记录 SDK 原件、overlay、生成 probe 和 manifest 的 SHA-256。ARM link map 确认使用 overlay 的 endpoint/CH9/interrupt 对象，且未链接 stock endpoint/interrupt 库成员；ELF 含 `g6_secure_cleanup_diag`（120 字节）、`secure_cleanup`、`secure_tx_quiesce`、`secure_tx_wipe`、`secure_tx_rebuild` 与 `usb_cdc_secure_cleanup_tx`。另将安全清理扩展到生产 profile 的 USB 断连退会话路径；清理完成才回到等待新会话，任一阶段失败都会 fail closed。实际生产 profile 的离线链接与 harness 证据不等于板端所有权或清零读回验收。

`src/ps/src/g6_hmac_drbg.c` 实现 [NIST SP 800-90A Rev. 1 §10.1.2](https://csrc.nist.gov/pubs/sp/800/90/a/r1/final) 的 HMAC_DRBG-SHA-256，启动明确请求 256-bit security strength，并按 strength 检查 entropy_input/nonce 最小长度；另限定输入长度、最大请求长度和 1024 次重播种间隔。失败输出会清零，熵/provider 或密码运算失败时清除 DRBG 状态。生产接口启动时取 32 字节 entropy_input 和 16 字节 nonce；重播种时取 32 字节 entropy_input 与 16 字节 additional input。接口定义不是熵评估：provider 必须用实际源证明所需熵量、健康检查和故障锁止。仓库没有实际 provider 源码；任意 provider 也不会自动获得可信、认证或量产状态。

后续代码审阅发现，DRBG API 的参数/熵长度拒绝此前可能留下传入的旧状态，即使当前生产调用者会在失败后额外 uninstantiate。本轮将 fail-closed 约束下沉到 API：非法 instantiate/reseed/generate 输入会覆写 DRBG state；`RESEED_REQUIRED` 保留为正常门禁，状态仍可接受 reseed。新增用例验证先有效实例化、再用不足熵重新实例化/重播种、以及非法 additional-input 长度时旧状态均被清除，同时保留过期 counter 的正常 reseed 行为。该项是 API 层软件清理强化，不替代熵源健康检测或实际 provider。

熵源架构事实已按 AMD 官方资料核实：WP467 说明 Zynq-7000 没有为应用层 session key 生成提供的片上 silicon RNG，但用户可在 PL 实现 RNG；WP468 说明可编程安全逻辑要建立信任，依赖认证启动链，避免未授权 bitstream 替换熵源。项目源码搜索也没有找到 TRNG、PUF 或熵采集 IP/driver。故当前不能实现一个可信的纯 PS entropy provider；下一步必须检查实际 bitstream 和板卡原理图，确认 PL TRNG 或外接熵器件，再做熵评估、健康测试与安全启动绑定。[AMD WP467](https://docs.amd.com/api/khub/documents/~r0Z3L3XXjpo2pmVrIvd_g/content)、[AMD WP468](https://docs.amd.com/api/khub/documents/kpDj1NsgdFh10n3DhSxgdA/content)。这是器件架构边界结论，不是板上熵源存在性的测量结果。

NIST [HMAC_DRBG-SHA-256 示例向量](https://csrc.nist.gov/CSRC/media/Projects/Cryptographic-Standards-and-Guidelines/documents/examples/HMAC_DRBG.pdf)的三种情形共五组 64 字节输出纳入原生 C 回归：无附加输入的两次连续输出；带 personalization 的两轮 Generate，使用两组非空 additional_input；以及显式成功重播种后的输出，并检查重播种计数器由 1 复位、生成后增至 2。这样也覆盖了生产代码把主机 nonce 混入 DRBG 状态的路径。向量只验证确定性算法实现，不证明熵源、CAVP/FIPS 认证或目标板行为。

## 验证

`sim/tb/test_g6_hmac_drbg.py` 编译实际 DRBG、会话 HMAC 与 TinyCrypt SHA-256，NIST 连续输出向量、输入边界、未实例化状态、重播种门禁和擦除检查通过。`sim/tb/test_g6_production_profile.py` 编译并运行实际 `g6_usb.c` 的 `G6_PRODUCTION` 分支。C harness 覆盖：provider/熵/公钥启动失败关闭，公钥身份变化时 provider 在 mock 中拒绝解封装，provider 解封装错误后的共享秘密由调用者覆写，匹配身份时 KEM 走 opaque provider 接口。`nm` 另检查生产测试二进制没有私钥读取 API、应用侧 `eye_mlkem_dec`、开发 mailbox 或 `random_seed` 符号。固定模式测试熵不具备真实熵或存储安全属性。

2026-10-11 首版 production profile 用临时 fail-closed provider 完成 XC7Z020 ARM 交叉编译与链接：`build/vitis/g6_prod_profile_final_20261011/g6_usb/build/g6_usb.elf`，SHA-256 `fe3511229c4725abfb214784ea013b03c71dec512fe37eefa598742748e22a7b`；输入 XSA SHA-256 `46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`。manifest 标为 `external_provider_unvalidated`、`board_validated=false`，DRBG 和 G6 源码哈希匹配该次构建源码。ELF 含 DRBG instantiate/generate/reseed 入口；开发 mailbox、host seed、计数器和静态私钥数据符号为零。临时 provider 的初始化、密钥、熵接口全部返回失败；该产物不含可用熵源或密钥服务。

此前安全清理候选使用同一 XSA 和 fail-closed provider：`build/vitis/g6_prod_secure_cleanup_candidate6_20261011/g6_usb/build/g6_usb.elf`，SHA-256 `50baa8ba43fdb1a40d5cb3bf0f138e39a480893d1b6ce5958433c1aae7a7ce52`。输入 XSA SHA-256 为 `46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`，DRBG 源 SHA-256 `838f0dff03ad87e1fc77b21a9b6af79904e538aed552bf7cdbc453a4c5e71717`、provider 契约头文件 SHA-256 `e6df75b0a2f5f46c65dab90585bb8c763feebe65d6946ff06cad4b9355266f62` 与 manifest 匹配。manifest 的 `production_secure_cleanup=bounded_usbps_overlay_and_dma_gcm_frame_tx_callbacks`、`security_profile=external_provider_unvalidated`、`board_validated=false`；编译参数有 `G6_PRODUCTION` 和 `G6_SECURE_CLEANUP`，没有 `G6_AUTO_RECOVERY`。使用 Vitis 配套 `arm-none-eabi-nm` 检查，ELF 含 DRBG instantiate/generate/reseed 与 secure-cleanup 符号，未见开发 mailbox/host-seed 符号；link command 使用候选目录内的有界 USBPS endpoint/interrupt 对象。provider 的初始化、熵和私钥读取均故意返回失败，因此它不可用于启动视频，也不是生产 provider。

最新生产 G6 源码另收紧了硬件启动失败路径：相机或 CDC 初始化未成功时，在任何应用控制/TX 发送之前覆写 CPU-owned session、HELLO/ACK、TX 和 DRBG 状态，关闭 provider 并转入 `FAULT`。后续代码审计发现生产 `main()` 仍残留一次 CDC 初始化，成功时会重复初始化，失败时也会重复关闭 provider；另发现生产故障后若 USB 断开，断连处理可能把 phase 改回 `WAIT_HELLO`，但 provider/DRBG 已关闭。本轮将生产启动收口到单一入口，并让 `FAULT` 成为断连后仍保持的终态。离线 C harness 验证成功时 camera/CDC 各调用一次，provider 部分初始化失败、相机失败、CDC 失败各只清理一次并将软件对象归零；已进入 `FAULT` 时断连不再重跑清理或恢复握手态。没有误调用依赖已初始化 USB 驱动的异步 TX 清理。启动失败路径不擦写 frame/sealed 或 DMA 对象，因为它不宣称已经取得对应硬件所有权证明；硬件残留仍属于板端验收。

最新启动失败清理候选使用同一 XSA 和 fail-closed provider：`build/vitis/g6_prod_secure_cleanup_candidate7_20261011/g6_usb/build/g6_usb.elf`，SHA-256 `22e157cf2854f175ac2dc5b278a7c8e53d816a96d79952d48d04645f6648b0a8`。manifest 的 `src/ps/src/g6_usb.c` SHA-256 为 `252ab9be0e27cb4079d18e419ef676576ce2134bbb5759158210c8e0da2c723e` 并匹配工作树；编译参数仍只有 `G6_PRODUCTION`、`G6_SECURE_CLEANUP` 与 `G6_USB`，不含 `G6_AUTO_RECOVERY`；配套 Vitis `nm` 未发现开发 mailbox/host-seed 符号，link command 仍使用有界 USBPS 对象。manifest 继续标为 `external_provider_unvalidated` 且 `board_validated=false`，ELF 不是可用生产固件。

修复启动单次初始化后的候选在 `build/vitis/g6s8/g6_usb/build/g6_usb.elf`，SHA-256 `a04ae0656b738a70e34d1879dcd9147bc71f8be08e7dea36209fca0bea031aa3`；XSA SHA-256 仍为 `46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`。manifest 的 `src/ps/src/g6_usb.c` SHA-256 `a9c4017c18ea9794ee5243e9c6c01ba08ce1b90434ff63980c121da52e8ee22c` 匹配源码；`nm` 确认 DRBG 与 provider 接口仍链接，开发 mailbox/host-seed 符号未出现。构建使用较短的工作目录以避开 Windows HSI 深路径下 BSP 文件复制失败；manifest 仍标为 `external_provider_unvalidated`、`board_validated=false`，链接的 provider 是故意失败的临时实现。

追加生产故障终态门禁后的候选在 `build/vitis/g6s9/g6_usb/build/g6_usb.elf`，SHA-256 `431e135e14dadaccc80b3fe35ece552a9506b78c123c755d2253d2a937a3d011`；manifest 的 G6 源码 SHA-256 为 `a3f38d55f01747154e8fc75a7a8da42a6ba3a8c51920a8d673801351c42f4ca3`，XSA SHA-256 未变。该候选随后被 opaque-key provider 接口替代。

Opaque-key provider 接口和生产源列表收紧后的候选为 `build/vitis/g6s11/g6_usb/build/g6_usb.elf`，SHA-256 `5bc7b5c6b558adc8b51ec4aeb25c630d6a23a4fe42b9552e5abf4e87d0b3fd5d`；manifest 中 `src/ps/src/g6_usb.c` SHA-256 `f49a100dd14d1bf6b2db86c632a43b5d92b250d6b246139130e6f89afc8fe8dc` 与源码相符，XSA SHA-256 `46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`。生产 builder 不再编译 `m09_mlkem.c`，并把 `eye_mlkem_dec`、`eye_mlkem_check_sk`、私钥导出 API 设为硬失败门禁；ARM `nm` 确认这些符号及开发 mailbox/seed 均不在 ELF，DRBG/provider/secure-cleanup 符号仍在。相同 builder 的开发对照 `build/vitis/g6dev11/g6_usb/build/g6_usb.elf`（SHA-256 `ae7b83adacd4b85b59e2e251a4b26d5629040ff99f2272ca8b26d4001f3fe971`）仍含开发 decapsulation 和 JTAG mailbox。生产候选 manifest 仍是 `external_provider_unvalidated`、`board_validated=false`，临时 provider 故意 fail closed。

增加必需 DRBG/provider/secure-cleanup 符号检查，并在调用 provider 前先清零共享秘密输出区后的候选为 `build/vitis/g6s12/g6_usb/build/g6_usb.elf`，SHA-256 `f5ade2b395e51de3bc35b00022c9b2ce267479cfe530f80b502b4cb0e5db41ed`；`g6_usb.c` SHA-256 `99765b137a3726252ca7e33f54ab98a41b7d76c720b3726d3e6fa63675876556` 与 manifest 一致。builder 要求 instantiate/generate/reseed、全部 provider API、受限清理诊断与 cleanup callbacks 均链接，并拒绝应用侧 ML-KEM、私钥导出和开发 provision/seed 符号；该 ARM 构建通过全部要求。manifest 仍标记 `external_provider_unvalidated`、`board_validated=false`，临时 provider 故意 fail closed。

为补齐静态 CPU-owned 清理范围的地址证据，builder 现从最终 ARM ELF 校验并写入 `tx`（1472 B）、`hello`/`ack`（各48 B）、`session`（192 B）和 `production_drbg`（72 B）的 DDR 地址/尺寸，并检查地址对齐和对象范围不重叠。新版只读 AP0 Tcl 读回除 frame/sealed/TX 外，还检查 session transcript/key 字段（偏移64..144）、session nonce/counter字段（偏移144..184）及 HELLO/ACK 缓存；XSDB wrapper 从 manifest 取地址并校验 ELF SHA-256，只持久化零值状态，不输出缓冲内容。`session.h` 增加结构尺寸与偏移静态断言。后续 fail-closed 源码审阅又发现 SHA/HMAC/HKDF 参数拒绝可能留下调用方旧输出、`eye_session_init()` 收到空公钥时保留原 session，格式错误的 host Finished/command、command 序号认证失败以及 Finished/nonce 输出指针为空或被拒绝时也依赖上层清理。本轮将这些路径改为输出清零或 API 内退会话，并增加 7 个真实 C API 回归用例。新候选 `build/vitis/g6s16/g6_usb/build/g6_usb.elf` SHA-256 `6fb9782a18718221b947adc0150e7e432c945fdcf125bcdd24b8560e2779cf08`，link map SHA-256 `3d8b5af0a953a51350c7c8d94649283610939b420a85645856bf338b5f39ab23`；`session.c` SHA-256 `6379414be57eb982e0c6e53946184c4b4184505e6ff079405b38f95dc26e2188` 与 manifest 一致，`session.h` SHA-256 `6248650ffdec4cd29c852f2949bee26bfed51c4534b3f13a2f134a96844b5b65` 也一致。manifest 的 `owned` 含上述地址范围，仍为 `external_provider_unvalidated`、`board_validated=false`。新增采集器/Tcl/session fail-closed 测试通过；全量电脑端回归 **140/140** 通过（271.034 秒）。Tcl 使用 mock AP0，实际板端读回尚未执行，临时 provider 仍故意 fail closed。

2026-10-11 安全回归补充：新增 1 个 C API 用例覆盖已认证包重复、乱序、过旧序号及错误 session ID，确认拒绝时 replay window 不前进、有效会话密钥不被清除。另修复主机 `HostSession.verify_board_finished()` 在 `decode_control()` 抛错时不退会话的缺口：畸形 Board Finished 现关闭会话并覆盖旧 video/control key bytearray，新增引用级清零断言。G6 定向 pytest 为 12 passed、4 subtests；相关主机 G6/M09/M10 测试 16/16；`session.c`、DRBG、协议及 SHA-256 依赖通过 GCC `-fanalyzer -fsyntax-only`。补齐 Icarus Verilog 临时工具和 Vivado 路径后，全量 `sim/tb` pytest 最终为 147 passed、83 subtests passed，耗时 309.29 秒，无警告。另将误以 `test_` 开头的 Keccak 向量辅助函数改名为 `make_vectors`，避免把返回数据的 helper 误计为测试；真正的 Keccak x4 RTL 测试通过。此前因缺少 `iverilog`/`vvp` 未启动的 RTL 项现均通过。该轮修改包括 host/handshake.py 和回归测试，没有改变 g6s16 ELF。Tcl 使用 mock AP0，实际板端读回尚未执行，临时 provider 仍故意 fail closed。

## 主机握手临时秘密生命周期（电脑端）

`src/host/m09.py` 现在把 ML-KEM keygen/encaps/decaps 的私钥或共享秘密返回到可覆写的 `bytearray`；原生 C 输出缓冲仍在返回前清零。`src/host/handshake.py` 将 HKDF 中间值和 56 字节派生材料放在可覆写缓冲中，退出 `derive()` 时清 PRK、T1、T2 与上下文；`HostSession.begin()` 在成功、重复 transcript 拒绝或异常退出时清本次拥有的 encapsulation coins、shared secret 与完整派生材料。生产 G6/M10 主机入口在调用后也清传入的 coins 缓冲；离线 board 测试路径清 decaps shared/material 和私钥缓冲。握手会话关闭时，先前持有引用的 video/control key 缓冲会被覆写后再从 session 释放。

验证覆盖：`test_g6` 新增成功握手、关闭及重复 transcript 拒绝后，对 coins/shared/material/key 引用逐字节检查为零；当前针对性结果为 G6 15/15、演示 12/12、M09 NIST KAT/1000 次重复测试通过、M10 KDF/会话互操作通过。该改动只减少应用层可控缓冲的保留时间。Python `hmac.digest`、解释器、分配器和底层密码库仍会产生不可直接覆写的临时副本；因此不宣称 host 全进程清零或抗内存取证，也不改变板端 provider/熵源/密钥存储缺口。

2026-10-11 后续收紧 M09/M10 开发板 JTAG 测试器的本地密钥传输生命周期：mailbox 请求、数据输入和板端回复改用唯一临时文件，退出时覆写、flush/fsync 后删除；M10 的回复中会话材料解析到可覆写缓冲并在调用后清理，M09/M10 本地私钥副本、M09 解封装结果及 M10 Finished/command 临时缓冲也改为可覆写对象。装载命令发出前即标记 AP0 密钥区可能已装载，即使 XSDB 超时或返回错误，finally 仍会尝试板端 clear；新增 fake-XSDB 测试覆盖临时文件清理和两种工具的装载失败清理路径；提交包策略现将 `board/output/` 整目录硬拒绝，ZIP 校验器也拒绝其中的条目。M09 测试 keyset 写入再采用独占锁，先原子替换公钥和 pin，最后原子替换 `private.bin`；封装流程要求该私钥提交标记存在，失败注入确认私钥提交前的半成品会被拒绝且可重试。该测试没有连接板卡，AP0 清零结果仍待实测。`board/output/m09/private.bin` 是为重复开发测试保留的忽略文件，不是生产密钥；临时文件覆写删除不保证对 SSD、日志文件系统或强制终止场景的不可恢复擦除。若进程被强制终止，keygen 锁文件可能遗留并需先人工检查。

另以同一 XSA 和当前构建脚本编译开发 profile：`build/vitis/g6_dev_profile_final_20261011/g6_usb/build/g6_usb.elf`，SHA-256 `f80f9fd014d0ee6d329b8149c7a12cb62e881801eb10858e722d807f236dff1c`。开发 ELF 保留 mailbox 和旧开发随机状态，未编译/链接 DRBG 源；生产 ELF 则相反。两个 manifest 分别标记 `development_jtag_mailbox` 与 `external_provider_unvalidated`。两个构建的 `g6_usb.c`/DRBG 源码哈希均匹配；该对照验证 DRBG 仅进入显式生产配置。

本节最新全量电脑端回归 `.venv/Scripts/python.exe -m pytest -q sim/tb` 为 **163 passed、87 subtests passed**，耗时 **312.72 秒，无警告**；Icarus Verilog 通过哈希核验的用户范围安装包解到临时目录运行，Vivado 通过 `VIVADO_ROOT` 指定，工具路径未写入仓库或持久化 PATH。覆盖 host 临时秘密与 JTAG 传输文件清理、M09/M10 私钥和回复直接读入有界可覆写缓冲、DRBG 输入失败状态覆写、opaque-key provider 身份/失败门禁、输出区调用前清零、生产启动单次初始化、启动失败清理，SHA/HMAC/HKDF 非法参数输出清零、session 无效重初始化及 malformed Finished/command、序号错误、空输出指针和拒绝路径输出清零；USB TX 仅在清理回调确认释放后覆写，前序清理失败时不越权写入。M09/M10 fake-XSDB 验证请求/数据/回复临时文件退出后已覆写并移除，首次私钥装载失败也会尝试 AP0 clear；打包策略测试覆盖误跟踪的 `board/output` 文件与包含此目录条目的 ZIP 拒绝；M09 keyset 失败注入覆盖私钥提交前拒绝使用及清理后重试。生产 profile C harness 在 `-O0` 与 `-O3` 均通过；新增可覆写文件读取与大小上限回归；manifest 驱动的只读清零读回工具测试拒绝错 ELF、地址重叠、非零范围、重复总结和不完整/夸大的证据。故障后断连保持终态及全部既有 RTL/协议用例也通过。production/development ARM profile 均完成重建，生产 ELF 必需/禁止安全符号 link gate 通过。电脑端回归不代表熵源、密钥服务、host 全进程清零或板端安全验收；实际 AP0 读回仍待板测。

本轮继续收紧开发主机密钥生命周期：G6 USB 验收运行器现在将 `private.bin` 直接读入有界 `bytearray`；纯软件 `prepare_demo.py` 统一使用 M09 的私钥最后提交写入和 keyset 校验，修复半成品 keyset 无法恢复的问题，并覆写生成种子、临时私钥、封装 coins、共享秘密和解封装结果。回归注入“上一轮留下公钥/pin、私钥未提交”状态，确认可以安全重试且各可控缓冲归零。以上是课程/竞赛演示的主机端改进，不声称 Python/密码库内部副本可清除，也不补足板端熵源/provider 或安全存储。

G6 开发态 JTAG provisioning 的临时随机种子文件现在使用统一的暂存文件清理器，退出前覆写、flush/fsync 并删除；内存种子也在成功和失败路径覆写。Fake XSDB 通过删除钩子核验磁盘内容在 unlink 前为零。没有调用真实 XSDB 或访问板卡。

G6 JTAG loader 与 `provision_g6_jtag.tcl` 现在都会拒绝 private-key、seed、ready、status ELF-owned DDR 区域之间的重叠，避免错误符号布局造成跨缓冲写入。Python fake-XSDB 用例验证拒绝发生在启动/连接命令之前；Vivado `xtclsh` 使用合成输入做了真实 Tcl 预检，输出了重叠拒绝信息且未进入 provisioning。该结果仍不是 AP0 实板地址读回。

M09/M10 的同类保护现已扩展到 ELF builder、主机 JTAG runner 和 Tcl runner：mailbox、私钥及输出区必须是有效且互不重叠的半开 DDR 区间，拒绝发生在 XSDB/连接前。Python 回归覆盖有效相邻区间、重叠和无效长度；Vivado `xtclsh` 使用合成重叠地址分别预检两份 Tcl，均报告拒绝且没有完成标记。该检查验证的是门禁逻辑，不证明实际 ELF 地址或板端清零。

## 仍未完成

必须由平台设计与板卡验证补齐真实 entropy source、SP 800-90B/90A 相关的源评估与健康/重播种策略、长期私钥生成/封装/持久化/身份绑定/轮换/RMA/销毁、secure boot/JTAG 生命周期、复位与掉电行为、PS/PL/DDR/DMA/USB 全域清理及读回。软件接口现要求私钥留在 provider/key-service 边界，但实际 provider 尚未实现或审查；还要证明共享秘密及会话密钥在 PS 内存中的保护和清理。接口隔离只阻止生产 profile 误走开发 mailbox 和主机 seed 路径，不是生产安全认证或 G6 验收。
