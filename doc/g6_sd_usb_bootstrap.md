# G6 开发态 SD 启动与本地 USB 初始化

2026-10-15 用户明确同意：SD 仅存启动程序，可信 Windows PC 在每次冷启动后通过本地 USB
提供专用测试身份与新随机种子，替代 JTAG。此功能不等于脱离 PC 的自主安全启动。

## 边界

- 仅显式 `G6_DEV_USB_BOOTSTRAP` 固件启用，与旧 JTAG/default 和 production provider 隔离。
- 不向 SD、BOOT.BIN、源码、EXE、配对 JSON 或日志写入真实私钥/随机种子；不烧 eFuse。
- PC 持有开发测试私钥、知道随机种子，USB 链路明文传输这些开发材料。
  本地 PC、USB 线缆及物理设备必须可信；公开 pin 比对不是对未初始化 USB 设备的认证。
  不宣称生产安全或针对恶意 PC 的前向保密。
- 手机 schema2、suite2、type10/type11、Finished、START/STOP/REKEY 与视频格式保持不变。
  网络转发器不允许手机发送本地 bootstrap 记录。
- 旧 G0 SD/LED/十分钟例外验收不替代 G6 本次真实 SD 冷启动及认证视频验证。

## 冻结的 EYBS v1

仍使用 USB 外层 `channel=1 | length_BE16 | payload`，payload 最大 1036 字节。
bootstrap 与原 `EYPQ` 控制消息使用不同 magic，不能作为业务消息转发。

| 头字段 | 字节数 | 要求 |
| --- | ---: | --- |
| magic | 4 | ASCII `EYBS` |
| version | 1 | 1 |
| type | 1 | QUERY=1、DATA=2、STATUS=0x81 |
| offset | 2 | 大端；DATA 必须连续，STATUS 为已接收长度 |
| length | 2 | 大端；必须等于实际 body 长度 |
| total | 2 | 大端；固定 1696 |

总材料按顺序为 `public_pin[32] || ML-KEM-512 secret_key[1632] || startup_seed[32]`。
每块 DATA 1..1024 字节，每块均等待 STATUS 确认，不流水并发；seed 每次实际装载前由 PC OS 新生成。
PC 在发送任何秘密前，先严格验证 QUERY 响应，并检查本地 SK 内公钥与 schema2 配对公钥/pin 一致。
注意两种哈希不同：应用公钥 pin 使用 SHA256；SK 内部 `H(ek)` 使用
SHA3-256，按 [FIPS 203 §4.1](https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.203.pdf) 校验，不能混用。
未初始化设备不持有身份，不能借此 QUERY 证明其真实硬件身份。

QUERY：offset=0，length=0，total=1696。STATUS：length=34，body 为
`state[1] || code[1] || public_pin[32]`；code=0 成功、code=1 失败。

| state | 值 | STATUS offset | STATUS pin |
| --- | ---: | --- | --- |
| WAIT | 0 | 0 | 全零 |
| RECV | 1 | 已接收字节数 | 全零 |
| READY | 2 | 1696 | 已装载身份的 SHA256 公钥 pin |
| FAULT | 3 | 0 | 全零 |

## 状态与清理

仅 DTR=true 后处理 bootstrap。WAIT 接受 QUERY 或从 offset=0 开始的 DATA；
首次 DATA 启动不可续期的绝对十秒期限。头错误、越界、乱序、重复块、私钥或 pin 校验失败，
以及 RECV 期间断连/USB epoch 改变/超时，清除暂存及秘密后进入终态 FAULT。
WAIT 尚未收 DATA 的断连允许之后重新连接；不得接收未经初始化的业务会话。

完整材料须通过私钥一致性及公钥 SHA256/pin 核对后才进入 READY；擦除收包暂存和 CPU-owned 副本。
READY 允许只读 QUERY，禁止重新装载，DATA/非法 bootstrap 不能改变身份或复活故障。
正常 DTR/epoch 断连、STOP、REKEY 清理业务会话但保留本次启动身份，沿用已有 G6 行为；
真实 FAULT 不允许用 bootstrap 重新初始化，需物理重新启动。
收包路径仅擦除已归 CPU 所有的范围，不越权覆写仍归 DMA 所有的缓冲。
Python、系统驱动或硬件临时副本的完整物理清除不由本实现保证。

## PC 接入

使用显式 `run --dev-usb-bootstrap --dev-identity-file <本机私有文件>`；
要求配置具体串口，拒绝自动枚举后静默注入。普通 run 不读取身份私钥、不探测此协议。
先拒绝已有监听并完成原账号/TLS 配置检查，再独占打开 CDC、设置 DTR、QUERY/必要装载；
成功后正常关闭该句柄，才启动转发服务。

每次已认证观看者取得 CDC 时，再独占打开并 QUERY：READY 核对 pin 后返回真实串口句柄给原 relay；
WAIT 才重新读取受 ACL 保护的显式私钥并生成新 seed。错误或 FAULT 静态脱敏失败，
不得重刷/JTAG 注入/抢占其他进程。沿用原串口清理，避免新增持久句柄租借抽象。

## 构建与实际验收

复用启用 SD0 的匹配视频 XSA、FSBL 和原 `--boot-images`，不拼接其他工程的 FSBL/bit。
独立 profile、源码/ELF/BOOT 哈希、ARM startup 和 Bootgen 分区检查先在 PC 完成。
写卡仅替换确认目标卡上的 BOOT.BIN：备份旧镜像，排他创建新文件、flush、读回核对，
再由用户安全弹出/拔插复核持久性。不得格式化或写原始磁盘。

真实验收须用户将卡放回、设置 SD 启动、完全断电后上电，并从 UART 记录只读 boot mode、
开发 profile WAIT/READY；不接 JTAG，PC 以 USB 初始化后完成原 suite2 认证视频。
重连、再次冷启动、新随机材料、错误/半包拒绝分别记录，不能以 JTAG 暖启动或模拟器替代。
