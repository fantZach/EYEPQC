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

## 1.3.1 READY 句柄交接修正

2026-10-16 主聊天实板报告首次开发初始化成功，随后观看连接分别出现 QUERY 超时、
OPEN 后非法记录、再 QUERY 失败。本 PC 代理没有操作硬件，不将下列离线复现称为这些
现场失败的唯一根因或实机已修复。

发现确定的 PC 缺陷：开发 factory 已完成 DTR 清理、QUERY/READY 并返回高 DTR 的真实句柄，
`Relay.handle` 随后又无条件切 DTR false→true、清空缓冲并等待 250 ms，制造多余 USB epoch。
新测试先在旧实现失败：读者启动前检测到 `[False, True]`，而应为 `[]`；
`Ran 1 test in 0.318s; FAILED`。最小修复仅将原 DTR/reset 初始化放回普通 factory 分支，
准备好的开发句柄直接交给转发循环；取消/异常后等待并关闭自有句柄的逻辑未改变。
没有自动重试 QUERY、忽略 ACK、放宽记录解析或恢复 FAULT。

修正后的定向结果均为退出码 0：

- `test_dev_usb_bootstrap.py`：17/17，3.616 秒；含 READY 不读私钥、NIST H(ek)、
  factory 取消收尾及新交接检测。
- `test_relay.py`：21/21，12.141 秒；普通 relay 的 DTR 低电平等待、控制转发、STOP 排空、
  读取取消、单观看者和故障清理仍通过。
- 新 1.3.1 EXE 的隔离 managed config：1/1，7.489 秒。
- 新 1.3.1 EXE 的隔离证书/账号/配对离线 check：1/1，3.379 秒。

按主聊天批准将 CLI/安装器版本升到 1.3.1，在新路径离线构建，不覆写 1.3 产物：

| 候选 | 字节数 | SHA256 |
| --- | ---: | --- |
| `build/pc_cli/dist/eyepqc-1.3.1.exe` | 10291539 | `8DEB509EC27C4D7C54E84CC607F2CDBAA9899A1329802A9F8C926F979EADF8EE` |
| `build/pc_installer/dist/EYEPQC-Setup-1.3.1.exe` | 12132570 | `5E34F9C80AB6C0CC220F5D43595439FC355E8431F279FCEEBF180C72D6D29677` |

README、打包默认值及 frozen/lifecycle 测试引用已同步版本。源码与产物已冻结交还主聊天；
没有重跑不受影响的完整 PC suite，没有安装或改动实际用户数据/服务/USB/SD。
Board 代理另外分析 READY ACK 完成边界与 DTR 关闭的竞态；其证据以 Board 报告为准。
两端修正后仍需主聊天重新进行无 JTAG 冷启动、USB 初始化、认证播放与重连验收。

## 1.3.2 认证期间断开握手修正

主聊天反馈匹配 SD 修正后能够播放约 45 fps，同时前置出现一次 QUERY 超时及
`websockets/asyncio/connection.py:889` → `asyncio/server.py:196` → `server.py:527`
的 `AssertionError`。本 PC 代理只做离线/本机临时回环测试，没有触碰正在播放的服务或硬件。

已通过本机固定版本 websockets 15.0.1 的真实 TLS/socket 复现后者：后台 scrypt 验证尚未完成时，
客户端断开使 protocol 进入 CLOSED；验证返回后库仍试图发送 101，违反 CONNECTING 断言。
新正式回归先在旧版本失败（1 项/0.776 秒，精确相同断言栈），修正后单测
1 项/1.405 秒通过，且确认验证锁释放、旧握手不触发 USB、服务器注销旧连接、下一连接正常。

最小修复在 `Relay.authorize` 的 worker 收尾及 `verifying=False` 后、任何响应/owner 更新前，
检查公开的 `connection.state`；不再 CONNECTING 则抛出 `asyncio.CancelledError`，
沿库既有取消路径终止该握手，不用 HTTP 错误替代已失效的 101。
保留等待后台验证线程收尾、限速、认证、409 明确接管和 fail-closed 行为。

### QUERY 重试方案明确未实施

经 PC / Board 互审和主协调确认，撤销最初考虑的零字节超时自动 QUERY 重试方案，
没有添加重试、quiet-window、额外 barrier、接收过滤或静默吞 ACK。
EYBS v1 无 request-id：首 ACK 恰好迟到后重查会多出一个相同 STATUS，
WAIT 下可能污染 DATA ACK，READY 下可能污染业务读者；短暂安静不能可靠证明无在途响应。
原 QUERY 仍单次、绝对两秒有界失败，partial、FAULT、错误状态/格式或 ACK 一律拒绝，DATA 从不重发。

首次现场 QUERY 超时的唯一真实原因仍未确证。Board 另行修复开发 profile 的重复 DTR 请求
无条件抹 RX 的确定错误；本报告不以该静态缺陷或软件测试替代新 SD 实板重验。

### 定向验证与新候选

实际结果均为退出码 0，没有重复不受影响的完整 PC suite：

- `test_accounts.py`：13/13，22.558 秒；含真实 TLS/socket 断开、后续连接、认证、限速、接管、清理失败保护。
- `test_dev_usb_bootstrap.py`：17/17，3.698 秒；QUERY 路径未修改。
- `test_relay.py`：21/21，14.229 秒。
- 新 1.3.2 EXE 隔离 managed config：1/1，7.465 秒。
- 新 1.3.2 EXE 隔离材料离线 check：1/1，0.783 秒。

CLI/安装器版本及 frozen/lifecycle 测试引用同步为 1.3.2，现有本机工具离线构建：

| 候选 | 字节数 | SHA256 |
| --- | ---: | --- |
| `build/pc_cli/dist/eyepqc-1.3.2.exe` | 10289332 | `A0B909FF674CC4902672476B98678196F31CFFE3284ECFA32A906132B3BCE160` |
| `build/pc_installer/dist/EYEPQC-Setup-1.3.2.exe` | 12129259 | `6A340B1F3C7ACA3788BC34FA62860916671D0BC54225B6C8A5994FFC5E45DA17` |

旧 1.3.1 两份产物保留并重新复核 hash 与上表前一节一致；未安装、部署或修改真实 settings/材料。
源码/产物冻结交还主聊天，后续安装和新 SD 现场验证由主聊天安排，不把本轮软件结果称为新版本实机验收。

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

### 1.3.1 主协调实际升级（2026-10-16 12:34 UTC+8）

子代理源码及产物冻结后，主协调再次确认没有eyepqc进程或8765监听，将已安装1.3.0排他备份为
`build/pc_cli/installed-1.3.0-before-dtr-fix-20261016.exe`，核对新Setup哈希后离线升级。
安装退出0，安装EXE哈希与上述1.3.1候选一致，`--version`为1.3.1，默认离线check为CONFIG_OK。
settings、原六项运行材料和测试身份共8项文件哈希前后一致，用户PATH完全不变；未启动服务或访问COM7。
安装日志 `build/pc_installer/install_1.3.1_dtr_fix_20261016.log`；真实视频仍须与更新的SD固件联测。

### 后续实际播放及未修复的握手竞态

修正版SD上板后，用户反馈Android正常显示45fps；COM4也捕获WAIT/READY mode0x05。
同次用户日志的首个viewer仍在OPEN前2.282秒TimeoutError，后一次连接成功；期间出现
websockets `connection.py:889 -> asyncio/server.py:196 -> server.py:527` AssertionError。

PC子代理只读诊断并以真实authorize+延迟verify+客户端提前断连的纯软件fixture复现相同堆栈：
连接await期间成为CLOSED，websockets 15.0.1仍尝试发送101，违反其CONNECTING断言。
验证锁释放，USB factory没有调用；这不证明密码或ML-KEM失败，也不能解释首次USB QUERY超时。
仅临时wrapper验证非CONNECTING时取消握手能消除该断言且下一连接成功，未改源码、未打包或部署。
首个QUERY的250ms DTR等待+2秒STATUS上限与耗时相符，但实际USB时序仍不足以唯一定位。
当前手机播放未被打断，本报告不宣称这些剩余问题已修复或完成持续/重连验收。
