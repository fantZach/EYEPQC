# G6 生产安全 profile 隔离进展

更新：2026-10-11。本次只做源码、构建脚本和电脑端测试；未连接板卡、未改 SD/Flash/eFuse。**生产安全仍未通过。**本实现将开发态装载与生产服务接口分开，尚未提供或验证目标板的熵源、密钥存储或可信启动实现。

## 本次实现

- 默认开发 profile 保留现有 JTAG 测试 mailbox 与 host-seed/HMAC 随机实现，保持既有开发流程。
- 显式以 `G6_PRODUCTION` 编译时，固件不定义 `g6_sk_load`、`g6_seed_load`、`g6_ready`，也不含静态 `private_key`、`random_seed` 或 host-seed 派生的 `board_random()` 路径。
- 生产 profile 在启动 USB/摄像头前调用外部 `g6_production_security_init()` 和密钥服务；任一步失败即停机，不开始枚举。HELLO 随机数完全来自 `g6_production_random_bytes()`；随机服务报错时擦除输出且不发 HELLO_ACK。
- 生产 profile 启动时只在栈上临时读取密钥，用 ML-KEM 检查并固定公钥身份后清除副本。每次 KEM 解封装重新从 provider 读取、验证并比较公钥身份，之后清除栈上的密钥和公钥哈希。密钥服务失败或返回另一设备身份时拒绝解封装。严重协议错误关闭 provider。
- 新增 `--g6-production-provider <source.c>` 构建入口。若未给出该源文件，构建继续生成明确标为 `development_jtag_mailbox` 的开发 profile；显式给出时，manifest 标为 `external_provider_unvalidated` 并记录 provider 源码 SHA-256。外部实现缺失时，生产链接因 provider 符号未定义而失败。

provider API 的注释要求其熵/DRBG 启动检查和密钥服务可用性失败时 fail closed，但接口名称或返回值本身不能证明实现符合要求。仓库没有实际 provider 源码；传给构建器的任意 provider 也不会自动获得可信、认证或量产状态。

## 验证

`sim/tb/test_g6_production_profile.py` 编译并运行实际 `g6_usb.c` 的 `G6_PRODUCTION` 分支。C harness 用受控 provider 失败注入覆盖：熵服务启动失败不读取密钥、密钥接口部分写入后整块清零、随机服务失败不发送 HELLO_ACK、密钥身份变化时不解封装、匹配身份时每次 KEM 都经 provider 重新取钥。测试随后用 `nm` 确认生产二进制没有开发 mailbox 或 `random_seed` 符号。测试 provider 仅存在于 harness，固定模式和错误输出不具备熵或存储安全属性。

使用 `build_software.py --apps g6_usb --g6-production-provider <source.c>` 完成 XC7Z020 ARM 交叉编译与链接联调。为了不把未验证的 provider 冒充安全实现，此次 provider 是返回失败的临时 stub（SHA-256 `ff3c8e21ff727ff032d53ab571c6aa8e2aa4c53fcff5f44f6d5b7217f22c018c`）；产物 ELF SHA-256 `8ffea4519136b7691260f1ef487706fcf6346a056e87d64c7ecbe71a717c44b9`。manifest 标为 `external_provider_unvalidated`、`board_validated=false`，且绑定 provider hash；ARM ELF 符号表未找到开发 mailbox、`random_seed` 或静态 `private_key` 符号。临时 provider、manifest 和 ELF 位于本机忽略的 `build/`，未进入 Git/审阅 ZIP。

环境完整的 `python -m unittest discover -s sim/tb -p 'test_*.py' -v` 为 **126 tests / OK**，耗时 265.217 秒，包含新生产 profile harness、原开发 profile harness 及 M04/M05 原生 XSim。首轮调用漏设 `VIVADO_ROOT`、`IVERILOG`、`VVP`，M04/M05 两项报环境错误；保留原日志后按正式环境变量重跑，全量通过。生产 profile 尚未用真实板端 ARM provider 构建或上板。

## 仍未完成

必须由平台设计与板卡验证补齐真实 entropy source、SP 800-90B/90A 相关的源评估与健康/重播种策略、长期私钥生成/封装/持久化/身份绑定/轮换/RMA/销毁、secure boot/JTAG 生命周期、复位与掉电行为、PS/PL/DDR/DMA/USB 全域清理及读回。当前将私钥在解封装期间短暂复制到 PS 栈上；provider 需要明确并验证保护该副本的实际边界。接口隔离只阻止生产 profile 误走开发 mailbox 和主机 seed 路径，不是生产安全认证或 G6 验收。
