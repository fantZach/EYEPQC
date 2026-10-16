# PC 开发态 SD / USB 初始化交付记录

## 范围与状态

软件候选已完成，2026-10-16 继续核对并完成唯一一轮完整 PC 回归。
本记录不将软件测试、打包或跨语言 fixture 称为 SD 冷启动、实板视频或手机帧率验收。
本轮未安装程序、未打开真实 USB/串口、未读取真实身份私钥/密码，未修改用户 settings 或服务。

`doc/g6_sd_usb_bootstrap.md` 为冻结协议：SD 仅存启用开发 profile 的程序，可信 PC 通过
本地明文 USB 提供测试身份与每次实际 WAIT 装载前新生成的 32 字节 OS 随机 seed。
普通 `run`、原 schema2/suite2/type10/type11 与视频记录保持不变。

## 实现

- `pc/src/host/dev_usb_bootstrap.py`：严格 QUERY/STATUS 检查；WAIT 才读取显式本机私钥，
  验证链接路径、文件/父目录 ACL、1632 字节长度、内嵌公钥和 pin；分两块发送并逐块核对 ACK。
  READY 仅核 pin，不读私钥、不生成 seed、不重复装载；异常关闭自有句柄，尽力擦除自有可变缓冲。
- `eyepqc run --dev-usb-bootstrap --dev-identity-file <本机文件>`：两参数成对显式选择，
  要求具体 COM；先拒绝已有监听并完成账号/TLS 检查，初始化成功并关闭临时句柄后才启动服务。
  私钥路径不保存到 settings，安装器不扫描或迁移该文件。
- 认证观看连接的开发 factory 在线程中完成独占打开和查询；取消时等待有界初始化结束，
  由原清理路径关闭真实句柄。普通 relay factory 路径保留原行为。
- 手机网络控制路径继续拒绝 EYBS，不能借手机登录注入开发材料。

## 当前验证

命令：

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s pc/tests -v
```

2026-10-16 修正前完整回归结果：`Ran 114 tests in 60.791s; OK (skipped=2)`，进程退出码 0。
unified exec session 为 `56919`。共 112 项执行通过，2 项真实安装器生命周期测试因未显式
设置隔离 fixture root 而跳过；未把旧版本安装器验收算作 1.3 安装验收。

其中原 USB bootstrap 文件 15 项全部执行通过，覆盖：新 seed、两块/短写、清零、READY 不读私钥、
坏状态/ACK/ACL/长度拒绝、显式端口/成对参数、普通 run 不探测、已有监听优先拒绝、失败脱敏、
取消只清自有句柄，以及真实 PC 编码和 C 头状态机回包的三个序列。

跨语言序列为 WAIT→RECV→READY→READY、乱序后终态 FAULT，以及 READY 后再次 DATA 进入 FAULT；
本机 GCC 使用 `-std=c11 -O2 -Wall -Wextra -Werror` 编译 fixture。该 fixture 的 activation
刻意 mock，不证明真实私钥校验、ARM/USB 中断或物理板卡已经通过。
完整回归还执行了 1.3 EXE 的隔离配置/离线 check，未连接公网或真实板卡。

### 实际材料离线预检发现并修正的 guard 错误

主聊天仅在本机离线预检真实测试身份，发现本模块把 ML-KEM 私钥中的 `H(ek)` 字段误与应用
SHA256 pin 比较；该错误会在发送 DATA 前拒绝本来有效的身份，而不是板卡/SD 或密钥损坏。
旧合成 fixture 也把该字段造为 SHA256，故以上完整回归未能发现此错误，不能据它声称真实装载通过。

仓库 `board/src/third_party/mlkem/src/kem.c` keypair 及 check_sk 均通过 `mlk_hash_h` 处理该字段，
`src/symmetric.h` 明确其为 SHA3-256，并引用 FIPS203 §4.1 Eq4.4。已仅将内部字段比较改为
`hashlib.sha3_256(public).digest()`；应用 pairing/pin 继续 SHA256，未更换身份或手机协议。
参见 [NIST FIPS 203](https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.203.pdf)。

新增回归使用仓库公开的 NIST ACVP v1.1.0.35 / FIPS203 encapsulation 向量的真实 `dk/ek`，
直接调用实际 PC loader，不依赖 mock activation：修正前该测试确实失败
（1 项/0.485s，ValueError），修正后整个 bootstrap 文件 `16 tests in 3.438s; OK`。
同时证明正确 SHA3 内部字段可载入，把其替换成 SHA256 pin 会被拒绝。
未读取/打印主聊天真实私钥；测试向量不是实际运行身份。

按受影响范围只补定向、不重复全套：重建后 EXE 隔离配置测试 `1 test in 6.991s; OK`；
只读 PyInstaller archive 检查确认包内 `private_material` 的 `co_names` 包含 `sha3_256=True`。
这仍不代替真实 USB 发送/板端激活验证。

## 产物复核

2026-10-15 22:13（UTC+8）旧候选哈希复核与先前交付一致，但它包含上述错误，已保留为
`eyepqc-1.3-before-sha3-fix.exe` 与 `EYEPQC-Setup-1.3.0-before-sha3-fix.exe`，仅供隔离证据，勿部署。
旧 EXE SHA256 为 `09E6744F9CA8FD0D5B2C6F0ED9ADC966F39748A6C85264179CAA5259AFF96E89`；
旧 Setup 为 `FDEFA41AB3D45CAD3A693F1DD5D78B32FE874DE66E49CBC2002D4CAAC97C0BB6`。

修正后 2026-10-16 12:00（UTC+8）通过已存在的 PyInstaller / 已签名并固定 hash 的本机 Inno
离线重建，未下载、安装工具或调整杀毒设置；版本仍为 1.3.0，当前可用候选为：

| 候选 | 字节数 | SHA256 |
| --- | ---: | --- |
| `build/pc_cli/dist/eyepqc-1.3.exe` | 10291802 | `6EBD3B41272D5E5A584E91400D95F736272C7515703982E069AAFAF1EBA31BB0` |
| `build/pc_installer/dist/EYEPQC-Setup-1.3.0.exe` | 12131666 | `6ECDF43D283F0EF1F20860B2CFDD2BEFBCD56B9307F77F7EB7C62939AAA168FC` |

安装包仍不含真实材料，沿用六文件导入、保留用户数据/账号、当前用户 PATH 和离线编译流程。
未执行 1.3 安装/卸载，不代表代码签名、杀毒认证或安装生命周期已验收。

## 主聊天实机入口

主聊天独占硬件，在核对旧服务已正常停止、实际 COM 与受保护测试私钥之后执行：

```powershell
# 仅需配置不正确时显式修改；此命令本身不打开串口。
& ./build/pc_cli/dist/eyepqc-1.3.exe config set serial_port COM7
& ./build/pc_cli/dist/eyepqc-1.3.exe run --dev-usb-bootstrap --dev-identity-file <受ACL保护的本机测试私钥>
```

私钥应与现有 schema2 pairing 公钥/pin 一致，不重新生成或公开它。READY 时不重读文件；
冷启动 WAIT 才装载 fresh seed。出现 FAULT/超时不能 JTAG 掩盖或自动抢占进程。

尚待主聊天实测：无 JTAG 的真实 SD 启动、UART WAIT/READY、USB 初始化、原 suite2 认证视频、
重连及第二次冷启动。PC 知道测试私钥/seed，USB 为明文，未初始化 QUERY 不认证硬件；
这是可信本地 PC 开发方案，不是生产安全或脱离 PC 自主运行。

## 主协调本机部署补验（2026-10-16）

主协调仅将现有开发测试身份复制到当前用户受保护的
`data/private/board-test-identity.bin`，未改动源身份或公开配对。
真实 loader 首次预检拒绝后，区分公钥 pin 与内部 H(ek) 的哈希算法并定位上述错误；
同一文件在修正后再次通过目录/文件 ACL、长度、公钥、应用 SHA256 pin 和内部 SHA3-256 校验。
此时没有打开 USB，没有向板端发送密钥，也没有读取或更改账号密码。

确认无运行中的 EYEPQC 进程后，主协调将旧安装 EXE 排他备份到
`build/pc_cli/installed-before-sd-20261016.exe`，核对修正后 Setup 哈希后实际升级当前用户安装。
安装进程退出 0，安装 EXE 哈希与修正候选完全一致，`--version` 为 1.3.0，默认 `check` 为 CONFIG_OK。
安装前后 settings、六项原有运行材料及新增测试身份逐项哈希未变，用户 PATH 原值未变。
安装没有启动服务；实际 USB 初始化、冷启动和视频仍待板卡准备后验证，不能据安装成功标记通过。
升级日志为 ignored `build/pc_installer/install_1.3_20261016.log`；旧 EXE 和失败候选均保留。
