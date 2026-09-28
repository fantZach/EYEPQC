# EYEPQC 编程与调试步骤

## 1. 执行原则

- 每次只打通一条最短链路，不同时调试摄像头、DMA、密码和网络。
- 每个 RTL 模块必须先通过独立仿真，再进入 Block Design 和上板联调。
- 所有硬件输出都与软件黄金参考逐字节比对。
- 当前优先完成固定图片 AES-GCM MVP，再恢复摄像头明文链路和整机集成；先完成独立加密，再接入 ML-KEM 动态密钥。
- 按用户最新要求，以太网配置、PS GEM/PHY/IP、ping/echo、网络发送和联网验收统一放在最后编程阶段（第 21 节）；前面使用 JTAG/本地文件验证，不要求接网口。
- 第一版使用 Vitis Standalone（裸机）+ lwIP + PS GEM，不安装 PetaLinux。
- 第一版只在板端实现 AES-GCM 加密，解密、JPEG 解码、显示和录像均在主机完成。
- 每完成一个集成门禁点，保存可复现脚本、测试数据、ILA 截图和性能结果。

## 2. 建议工程目录

```text
EYEPQC/
├── README.md
├── doc/
│   ├── goals.md
│   └── steps.md
├── src/
│   ├── rtl/
│   │   ├── common/
│   │   ├── camera/
│   │   ├── crypto/
│   │   └── top/
│   ├── ps/
│   │   ├── include/
│   │   └── src/
│   └── host/
├── sim/
│   ├── tb/
│   ├── vectors/
│   └── scripts/
├── build/
│   ├── vivado/
│   └── vitis/
├── data/
│   ├── jpeg/
│   ├── kat/
│   └── captures/
├── board/
│   ├── xdc/
│   └── output/
├── report/
└── skill/
```

目录名和文件名使用英文。Vivado 生成目录、日志和大体积中间文件不要直接混入源码目录。

## 3. 模块依赖与集成顺序

```text
M00 协议与黄金参考 ───────────────────────────────┐
                                                   │
M01 板级基础工程                                   │
  ├─ M02 SCCB 摄像头配置                           │
  ├─ M03 JPEG/DVP 采集 ─ M04 异步 FIFO/AXIS ─ M05 DMA/DDR
  └─ M06 AES ─ M07 GHASH ─ M08 AES-GCM AXIS ──────┤
                                                   ├─ M13 整机集成
M09 ML-KEM 软件基线 ─ M10 会话与密钥管理 ─────────┤
M11 PS 网络与分包（最后接入）──────────────────────┤
M12 主机离线回放 / 最后接入网络接收 ───────────────┘

M14 ML-KEM PL 加速与性能优化
M15 可靠性测试、报告和竞赛交付
```

2026-09-27 用户调整优先级：`M00 → M01 已验证的 UART/DDR/时钟 → M06 开源 AES 核
→ 固定图片 AES-GCM MVP → 补齐 M01/G0 非网络子项 → M02～M05 → M07/M08 全 PL 数据通路`。
模块编号保留，执行顺序不再按章节编号机械推进；M01 网口、LED 实测和冷启动
30 分钟仍待验收，不因 MVP 提前而改成已通过。
用户随后要求以太网配置放到最后：先完成摄像头、DMA、离线 AES-GCM、ML-KEM/会话
参考及主机离线回放，再执行 M11 和联网集成验收。G0 的网络子项后置，不删除其判据，
也不因后置而将完整 G0 标为通过；M14 仍为全部门禁通过后的可选优化，不列入本轮第一版编程顺序。

## 4. M00：协议、数据格式与软件黄金参考

### 编程任务

- 固定第一版参数：ML-KEM-512、AES-128-GCM、96 位 Nonce、128 位 Tag。
- 定义 TCP 控制消息：版本协商、ML-KEM 密文、Finished、开始/停止、重协商和错误响应。
- 定义固定字节序的 UDP 包头，至少包含：
  - `version`
  - `flags`
  - `session_id`
  - `frame_id`
  - `packet_id`
  - `packet_count`
  - `jpeg_length`
  - `payload_length`
  - `timestamp`
  - `packet_sequence`
- 固定所有整数字段的网络字节序、字段宽度和版本号。
- UDP 包头作为 AES-GCM AAD，不加密但必须认证。
- 定义 Nonce：`session_epoch || packet_sequence`，总长度固定为 96 位。
- 在主机建立 AES-GCM 和 ML-KEM 软件黄金参考。
- 生成长度为 0、1、15、16、17、31、32、1400 字节的 AES-GCM 测试向量。
- 保存 NIST 标准测试向量、随机测试向量和篡改测试向量。

### 调试与完成判据

- 相同输入在不同运行中得到可复现的测试向量。
- AES-GCM 正确处理不足 16 字节的尾块。
- 修改 Key、Nonce、AAD、密文或 Tag 任一位后验证失败。
- ML-KEM Encaps/Decaps 得到一致的 32 字节共享秘密。
- 协议结构具有明确的最大长度检查，不使用未对齐的 C 结构体直接发送。

## 5. M01：领航者板级基础工程

### 编程任务

- 从正点原子领航者 Zynq-7020 官方工程中提取并核对：
  - XC7Z020 具体器件与速度等级；
  - P2 摄像头接口引脚；
  - PS DDR、UART、时钟和中断配置；
  - PL 时钟、复位和 IO 电平约束。
- 建立可用 Tcl 重建的 Vivado Block Design。
- 建立 Vitis Standalone 平台和最小裸机程序。
- 完成 UART 日志、系统时钟、定时器和异常处理。
- 建立统一的状态码、断言和统计计数器。

### 上板调试

- LED 心跳和 UART 启动日志正常。
- PS DDR 读写测试通过。
- PL 时钟和复位频率与约束一致。

PS GEM/PHY/IP 配置、网口接线、ping 和 lwIP echo 移至第 21 节最后执行。
已有 GEM 引脚/代码和历史测试保留，不在当前阶段调试网络；未验收网络仍记录为待办。

### 完成判据

- 一条脚本或一份明确步骤可以从空工程生成 bitstream 和裸机程序。
- 重新上电后可稳定运行 30 分钟，无异常复位和 DDR 错误。

## 5.1 当前优先：固定图片 AES 加密 MVP

### 最短链路

```text
主机图片 → JTAG 写入拥有的 DDR mailbox → PS 调度 PL AES-128
         → PS GHASH / 128-bit Tag → JTAG 回读 → 主机认证解密 → 字节比对
```

- AES 核采用 GitHub [secworks/aes](https://github.com/secworks/aes)，固定提交
  `80dc4718e1dcbbdb4b0dd1bdb393d8f7b98981dc`，保留 BSD-2-Clause 许可证与版权。
- 固定 `encdec=1` / `keylen=0`，只使用 AES-128 Encrypt；不自行重写 S-box/密钥展开。
- PS 通过 GP0 / AXI4-Lite 调用 AES；暂不接摄像头、DMA、网口或 ML-KEM。
- 保持 AES-128-GCM：PL AES 生成 CTR keystream 和 Tag mask，PS 执行 GHASH。
  不是 ECB 图片加密，也不是无认证 CTR；PS GHASH 后续在 M07/M08 移入 PL。
- 单次图片最多 512 KiB，保留长度检查、超时、复位和密钥零化；JTAG 传输/空闲时关闭 DCache，
  PS 独占处理期间启用缓存，完成后 flush/disable 再发布结果；不宣称视频吞吐已达标。
- 主机每次生成新随机 key/nonce，密钥只保存本地测试输出目录，不放入日志或 Git。
  JTAG 可读写密钥和内存，本演示不是安全部署或侧信道加固方案。

### 完成判据

- 原始开源 AES + AXI4-Lite 接口通过 NIST/随机块、通道错开/背压、复位与零化仿真。
- PS GHASH/GCM 对照 M00/NIST 黄金向量，覆盖空输入、尾块、大图片和篡改拒绝。
- 新 BD/bitstream/XSA/ELF 可重建，并在 CF7020B 上实际加密一张图片。
- 主机认证解密后的图片与原图 SHA-256 和全部字节一致；输出密文、Tag、还原图片及实测记录。
- 不能把软件模拟结果当作 FPGA 实测，不能把混合 PS/PL MVP 当作 M08 全 PL 已完成。

2026-09-27：此独立 MVP 已在 CF7020B 上通过，包含用户提供的 365954 字节完整 JPG
和 524288 字节 PNG 上限，认证解密后逐字节与 SHA-256 一致。实测与复现见 [图片 MVP](aes_mvp.md)。

## 6. M02：OV5640 SCCB 配置模块

2026-09-27：单时钟开漏 SCCB、ID 检查、有界重试、JPEG/YUYV 参数配置与关键项回读已编写；
引脚级仿真覆盖 20 次模拟初始化及故障退出，独立综合通过。复现/接口见 [M02](m02.md)。
heartbeat 测试按用户最新要求统一放回 `sim/tb/`，保留 M01 回归。
用户随后连接摄像头；原生 AXI GPIO 探针已读到 5640 ID，复测 20 次传感器复位配置通过。
用户断电重启后 ARM 调试恢复，两批严格串行复测共 40/40 次传感器配置通过，
覆盖两个 JPEG 分辨率、16 项关键回读及量化参数/VTS 切换；仍未验证实际图像采集。
首次测试有一次 4300 回读超时，原因未定位，故障记录保留；尚不宣称物理门禁完成。
模拟初始化和传感器 RESET 均不能代替下述 20 次实物断电冷启动判据。

### 建议文件

- `src/rtl/camera/sccb_master.sv`
- `src/rtl/camera/ov5640_reg_table.sv`
- `src/rtl/camera/ov5640_ctrl.sv`
- `sim/tb/tb_sccb_master.sv`

### 编程任务

- 优先复用并审查正点原子领航者 OV5640 例程中的引脚和初始化表。
- 实现 SCCB 起始、停止、写寄存器、读寄存器、ACK 超时和重试。
- 支持切换分辨率、JPEG 量化参数、HTS/VTS 帧周期和 JPEG/YUYV 输出格式；实际 FPS/PCLK 上板测量，不以配置值代替帧率验收。
- 支持读取芯片 ID，确认摄像头在线后再写初始化表。
- 初始化失败时保持视频采集模块复位并上报错误。

### 仿真与上板调试

- 仿真检查 SCCB 时序、ACK、超时和重复起始条件。
- ILA 观察 SCL/SDA，确认芯片 ID 和关键寄存器回读值。
- 先配置低分辨率 JPEG，再逐步切换到 640 x 480。

### 完成判据

- 连续冷启动 20 次均能读到正确芯片 ID 并完成初始化。
- 错误接线或未插摄像头时可超时退出，不会永久卡死。

## 7. M03：DVP/JPEG 字节采集模块

2026-09-27：用户要求恢复按 steps 推进，不建立临时 BRAM 快照旁路。
PCLK 域采样、JPEG 段长度/标记检查、2 MiB 帧长保护和错误统计已编写，
真实 JPEG 激励连续 1000 帧逐字节仿真通过，含截断/空帧/超长/异常 VSYNC 与故障恢复；
用户之前的 JPG 也已作 DVP 激励比对；OOC 综合为 184 LUT/394 FF，无 latch/BRAM/DSP。
这些不是摄像头实拍或物理门禁结果，见 [M03](m03.md)。
下一步 M04 FIFO/AXIS → M05 DMA/DDR，再验证真实 JPEG 保存及 ILA/实际 FPS。

### 建议文件

- `src/rtl/camera/dvp_capture.sv`
- `src/rtl/camera/jpeg_marker_check.sv`
- `sim/tb/tb_dvp_capture.sv`

### 接口

- 输入：`PCLK`、`VSYNC`、`HREF`、`D[7:0]`。
- 输出：JPEG 字节、有效信号、帧开始、帧结束、帧长度和错误标志。

### 编程任务

- 在 PCLK 域采样摄像头数据，并根据实际极性处理 VSYNC/HREF。
- 检测 JPEG SOI `FF D8` 和 EOI `FF D9`，处理标记跨周期情况。
- 统计每帧字节数并设置最大帧长保护。
- 记录缺少 SOI、缺少 EOI、意外 VSYNC、空帧和超长帧。
- 帧错误时丢弃当前帧，从下一个 SOI 重新同步。

### 仿真与上板调试

- 用真实 JPEG 文件转换成 DVP 激励，模拟 VSYNC/HREF/PCLK。
- 覆盖正常帧、截断帧、连续帧、空帧、超长帧和错误标记。
- ILA 观察 VSYNC/HREF、前 16 个字节、最后 16 个字节和帧长。

### 完成判据

- 捕获输出与输入 JPEG 文件逐字节一致。
- 连续 1000 帧没有帧边界错位。
- 错误帧不会污染下一帧。

## 8. M04：异步 FIFO 与 AXI4-Stream 适配

2026-09-27：采用原生 AMD XPM 数据/帧提交异步 FIFO 和 32/64-bit 字节打包，
错误/溢出帧只清理、不向 AXIS 发送半帧；统计通过原生握手快照跨域。
默认整帧缓存上限 64 KiB，超过上限拒收，不把 M03/协议的 2 MiB 上限当作已支持。
独立原生模型仿真与综合的复现、接口和时钟/复位约定见 [M04](m04.md)。
下一步仍按 M05 DMA/DDR 推进，不建立临时 JTAG 摄像头快照旁路。

### 建议文件

- `src/rtl/common/axis_byte_packer.sv`
- `src/rtl/camera/camera_axis_bridge.sv`
- `sim/tb/tb_camera_axis_bridge.sv`

### 编程任务

- 使用 AMD 异步 FIFO IP 或经过验证的 CDC FIFO，将 PCLK 域数据送入 AXI 时钟域。
- 将 8 位 JPEG 字节打包为 32 位或 64 位 AXI4-Stream。
- 正确产生 `TKEEP`、`TLAST`，必要时用 `TUSER` 表示帧开始。
- 实现下游背压、FIFO 高水位、溢出和丢帧策略。
- 添加帧计数、丢帧计数、最大 FIFO 水位和溢出锁存寄存器。

### 仿真与完成判据

- 随机拉低 `TREADY`，输出数据仍保持顺序和完整性。
- 覆盖 1～17 字节等各种尾包长度，`TKEEP/TLAST` 正确。
- 异步时钟频率和相位随机变化时无数据重复或丢失。
- FIFO 满时整帧丢弃并在下一个 SOI 恢复，不发送半帧。

## 9. M05：AXI DMA 与 DDR 双缓冲

本阶段的原生 DMA、缓存/所有权、复现及验证记录见 [M05](m05.md)。
`dma_crypto` 暂以 MM2S→S2MM 回环验证传输；AES-GCM AXIS 在 M08 接入，回环不当作加密。

### 硬件结构

- `dma_capture`：摄像头 AXI4-Stream 到 DDR，使用 S2MM。
- `dma_crypto`：DDR 明文到 AES-GCM 使用 MM2S，AES-GCM 输出到 DDR 使用 S2MM。
- 第一版采用两个 JPEG 帧缓冲区和独立密文包缓冲区。

### PS 编程任务

- 实现 DMA 初始化、启动、完成中断、错误中断和复位恢复。
- 明确缓存刷写/失效的方向和时机。
- 建立缓冲区所有权状态：`FREE`、`CAPTURING`、`READY`、`ENCRYPTING`、`SENDING`。
- 验证 AXI DMA 对变长 `TLAST` 帧的实际长度报告方式。
- 设置最大帧长；超长帧应丢弃并恢复 DMA。
- 提供 DMA 状态寄存器和错误位的 UART 转储函数。

### 调试顺序

1. 用 AXI4-Stream 测试发生器代替摄像头，发送固定短包。
2. 验证 DDR 中的数据和实际长度。
3. 测试不同长度、背压和连续帧。
4. 接入真实摄像头。
5. 压测 DMA 复位和错误恢复。

### 完成判据

- 10000 次不同长度传输无数据错误。
- 缓存打开时和关闭时结果一致。
- DMA 错误后无需重新下载 bitstream 即可恢复。
- 双缓冲不会发生采集端覆盖尚未发送的数据。

## 10. M06：AES-128 加密核心

### 建议文件

- `src/rtl/crypto/secworks_aes/`：固定版本的开源 RTL 与 LICENSE。
- `src/rtl/crypto/aes_axi_lite.sv`：最小寄存器接口、忙状态和零化。
- `sim/tb/tb_aes_axi_lite.sv`：使用实际开源核验证。

### 编程任务

- 复用 GitHub 开源 AES 核，不重写 AES 算法；MVP 只启用 AES-128 Encrypt，GCM 不需要 AES 解密轮。
- 明确 128 位数据、Key 和字节序映射，写入接口文档。
- 支持密钥装载完成、忙、输出有效和密钥清零。
- 优先采用资源适中的迭代结构，后续再根据吞吐率决定流水化程度。

### 仿真与完成判据

- 通过 NIST AES-128 Known Answer Test。
- 连续输入、多组密钥、复位中断和密钥更新测试通过。
- RTL 输出与软件黄金参考逐块一致。
- 综合后记录 LUT、FF、BRAM、时钟和每块周期数。

## 11. M07：GHASH 核心

### 建议文件

- `src/rtl/crypto/gf128_mul.sv`
- `src/rtl/crypto/ghash.sv`
- `sim/tb/tb_ghash.sv`

### 编程任务

- 实现 GF(2^128) 乘法和 GHASH 累加。
- 明确位序、约简多项式和输入块顺序。
- 支持 AAD、密文、长度块和不足 128 位的零填充。
- 独立输出 GHASH 中间值，便于逐块调试。

### 仿真与完成判据

- 通过 NIST GCM/GHASH 测试向量。
- 覆盖空 AAD、空明文、非整块 AAD 和非整块明文。
- 每一个中间累加值均可与软件调试模型比对。

## 12. M08：AES-GCM AXI4-Stream 加密 IP

### 建议文件

- `src/rtl/crypto/aes_gcm_encrypt.sv`
- `src/rtl/crypto/aes_gcm_axis.sv`
- `src/rtl/crypto/aes_gcm_regs.sv`
- `sim/tb/tb_aes_gcm_axis.sv`

### 接口约定

- AXI4-Lite：Key、Nonce、AAD、长度、启动、状态、计数器和清零。
- AXI4-Stream 输入：JPEG 包明文。
- AXI4-Stream 输出：密文，末尾追加 16 字节 GCM Tag。
- 输出长度固定为 `payload_length + 16`。

### 编程任务

- 组合 AES-CTR 与 GHASH。
- 正确支持 `TKEEP` 和不足 16 字节的最后一块。
- 固定 AAD 最大长度并拒绝超长 AAD。
- 禁止 Busy 状态覆盖 Key、Nonce 或 AAD。
- 每个包完成后递增硬件计数器并产生中断或完成标志。
- 实现零化命令，清除 Key、Nonce、中间状态和 Tag。

### 仿真与完成判据

- 覆盖 M00 的全部长度和篡改测试向量。
- 在随机 AXI 背压下密文和 Tag 始终正确。
- 连续包、重新装载 Nonce、重新装载 Key 和复位测试通过。
- 与主机软件 AES-GCM 完全互操作。

## 13. M09：ML-KEM-512 PS 软件基线

### 编程任务

- 选用符合 FIPS 203 的可移植 C 实现，固定来源、版本、提交号和许可证。
- 在 PC 先运行 KeyGen/Encaps/Decaps 和标准测试向量。
- 移植 Decaps 到 Cortex-A9 裸机环境，移除文件系统和操作系统依赖。
- 第一版在 PC 离线生成板卡静态密钥对：
  - 板卡保存私钥；
  - 主机保存并固定验证公钥；
  - 主机 Encaps，板卡 Decaps。
- 提供敏感中间值清零和错误返回。
- 测量 Decaps 周期数、耗时、栈和堆占用。

### 调试与完成判据

- PC 与 Cortex-A9 使用同一组测试向量得到相同共享秘密。
- 无动态内存版本优先；若必须使用堆，记录峰值并检查失败路径。
- 连续执行 1000 次 Decaps，无内存泄漏和错误结果。
- 无效密文不会导致越界、死循环或异常退出。

## 14. M10：KDF、会话与密钥管理

### 编程任务

- 从 ML-KEM 的 32 字节共享秘密派生：
  - `video_key`
  - `control_key`
  - `nonce_prefix`
  - `session_id`
- 会话状态机：`IDLE -> HANDSHAKE -> CONFIRM -> STREAMING -> REKEY/ERROR`。
- 在开始视频前验证 Finished 消息。
- 管理 64 位单调递增 `packet_sequence`，会话重建时更换 `session_epoch`。
- 设置重协商条件：计数器接近上限、用户请求、网络重连或错误恢复。
- 会话结束时清除 PS 内存和 PL 寄存器中的旧密钥。

### 完成判据

- 主机和板卡派生结果逐字节一致。
- 重放旧 Finished 或旧数据包会被拒绝。
- 断线重连后不会重复使用旧 Key/Nonce 组合。

## 15. M11：PS 网络、JPEG 分包与发送

模块编号保留，具体配置、编程和验收任务已移到文末第 21 节；此处不执行。

## 16. M12：主机接收、解密与显示程序

### 建议文件

- `src/host/protocol.py`
- `src/host/handshake.py`
- `src/host/receiver.py`
- `src/host/display.py`
- `src/host/record.py`

第一版可使用 Python 快速验证；吞吐不足时再将接收和解密部分迁移到 C/C++。
先实现本地文件/JTAG 输出的认证解密、JPEG 显示和离线回放；以下 TCP/UDP、重放窗口
及联网统计在最后阶段与 M11 接入，不把离线回放标成网络接收验收通过。

### 编程任务

- 建立 TCP 控制连接并执行 ML-KEM Encaps 和 Finished 验证。
- UDP 接收、包头解析、版本检查和重放窗口。
- AES-GCM 验证与解密；认证失败的数据不得进入组帧缓冲。
- 按 `frame_id/packet_id` 重组 JPEG，缺包时丢弃整帧。
- 检查 `FF D8`/`FF D9`，解码显示并可选保存录像或单帧。
- 显示实时 FPS、码率、丢包、乱序、认证失败和端到端延迟。
- 编写离线回放模式，使网络抓包可以重复用于调试。

### 完成判据

- 能正确显示固定 JPEG、摄像头 JPEG 和加密 JPEG。
- 注入丢包、乱序、重复、截断和篡改时不会崩溃。
- 认证失败帧不会被显示或保存。
- 下一完整 JPEG 帧到达后能自动恢复。

## 17. M13：整机集成门禁

正式整机集成必须验证实际依赖，前置板级条件不稳定时不进入上板集成。
用户授权的独立图片 MVP 可在 M01 已验证的 UART/DDR/时钟基线上先行；
该分支不包含网络/摄像头，不把 G0 标为通过，也不提前宣称 G1～G7 通过。
按最新顺序，先补齐 G0 非网络子项，再推进 G1 → G2 → G3 离线链路；
G0 的 PS GEM 网络子项与 G4 → G5 → G6 → G7 在最后阶段验收。
未通过项始终保留待办；网络后置不放宽长度、认证、密钥清理或故障恢复要求。

### G0：工具和板级基础

- Vivado/Vitis 工程可重建。
- UART、DDR、PL 时钟/复位、定时器正常，LED 与冷启动 30 分钟按 M01 验收。
- PS GEM/PHY/IP、ping/echo 正常（后置到第 21 节，不作为 G1～G3 离线链路的前置条件）。
- 非网络子项通过只允许离线链路推进；包含网络在内的全部子项通过后才标记完整 G0 通过。

### G1：摄像头离线采集

- DDR 中可获得完整 JPEG。
- 主机打开采集文件无解码错误。
- 统计 1000 帧的平均、最大帧长和实际 FPS。

### G2：AES-GCM 独立硬件验证

- 软件向 DDR 写入固定数据。
- DMA 经过 AES-GCM 后与黄金参考一致。
- 覆盖所有尾块长度和 AXI 背压。

### G3：摄像头到 DDR 到 AES-GCM

- 实时 JPEG 帧能够逐包加密。
- 软件解密后与加密前 JPEG 一致。
- 暂不启用网络。

### G4：明文网络视频

- 摄像头 JPEG 经 PS GEM 发送。
- 主机持续重组、解码和显示。
- 此阶段不启用 AES-GCM 和 ML-KEM。

### G5：固定密钥加密视频

- 插入 AES-GCM，使用固定测试 Key。
- 主机认证、解密和显示正常。
- 篡改包会被拒绝。

### G6：ML-KEM 动态会话

- TCP 完成 ML-KEM 和 Finished。
- 会话密钥装载到 PL 后开始视频。
- 重新握手、断线重连和密钥清零正常。

### G7：长期和故障测试

- 连续运行不少于 2 小时。
- 测试拔网线、主机退出、摄像头异常、DMA 超时和会话重建。
- 无死锁、Nonce 重用、缓冲区越界和未认证画面输出。

## 18. M14：ML-KEM PL 加速与性能优化

只有 G0～G7 全部通过后再开始，避免加速模块阻塞系统功能交付。

### 优化顺序

1. 记录 Cortex-A9 软件 Decaps 基线。
2. 加速 Keccak-f[1600]、SHA3/SHAKE。
3. 加速 NTT、逆 NTT、模乘和模约简。
4. 再评估是否实现完整 ML-KEM 控制器。

### 每次优化必须记录

- 握手延迟和周期数。
- LUT、FF、BRAM、DSP。
- Fmax 和关键时序路径。
- PS CPU 占用和 DDR 带宽。
- 优化前后端到端收益。
- 失败方案、原因和适用边界。

## 19. M15：调试观测与交付材料

### ILA 建议探针

- 摄像头：VSYNC、HREF、PCLK 域字节、SOI、EOI、frame_length。
- FIFO：写入、读出、level、almost_full、overflow。
- AXI4-Stream：TVALID、TREADY、TDATA、TKEEP、TLAST。
- DMA：启动、完成、错误、中断和复位。
- AES-GCM：start、busy、done、block_count、tag_valid、error。

### PS 运行统计

- `frames_captured`
- `frames_dropped`
- `frames_encrypted`
- `packets_sent`
- `camera_errors`
- `fifo_overflows`
- `dma_errors`
- `network_errors`
- `session_rekeys`

### 最终交付

- RTL、PS、主机端完整源码。
- Vivado/Vitis 可复现构建脚本。
- 仿真脚本、测试向量和黄金结果。
- 约束、bitstream、BOOT.BIN 和主机运行说明。
- 综合、实现、时序和资源报告。
- 分辨率、帧率、码率、加密吞吐率、延迟和稳定性数据。
- 大模型协作记录、自我纠错轨迹和 `skill/` 技能包。

## 20. 立即开始的工作清单

按用户调整后的以下顺序执行：

1. 建立工程目录和 Git 忽略规则。
2. 收集领航者官方 OV5640 示例、XDC 和 Vivado 版本信息。
3. 完成 M00 协议字段表和 AES-GCM 软件黄金参考。
4. 复用 M01 已验证的 UART、DDR 和时钟，补齐 LED/复位/冷启动；网口验收后置。
5. 优先导入 M06 开源 AES 核，完成独立仿真、最小 AXI4-Lite 与固定图片 AES-GCM MVP。
6. 补齐 M01/G0 非网络子项，再完成 M02 SCCB 芯片 ID 读取与 JPEG 初始化；可先独立编写/仿真，不以网口未连接阻塞开发。
7. 完成 M03/M04 仿真和 M05 摄像头 JPEG 到 DDR 的上板采集。
8. 完成 M07/M08，将 MVP 的 PS GHASH 迁入全 PL AES-GCM 与 AXI4-Stream/DMA。
9. 完成 M09/M10 离线 ML-KEM、KDF、会话和 Nonce/清理测试，完成 M12 本地 JPEG 认证解密、显示和回放。
10. 按依赖通过 G1 → G2 → G3 离线验收；网络门禁未完成时不宣称整机通过。
11. 最后执行下节以太网配置、M11、M12 联网接入和 G4～G7；验收后整理 M15 交付材料。M14 属于全部门禁通过后的可选后续优化。

## 21. 最后编程阶段：以太网配置与 M11 PS 网络、JPEG 分包和发送

前置为已验证的板级非网络基础、摄像头/DMA/离线加密链路及主机离线回放。
M09/M10 可先以本地向量验证，真实 TCP 握手与联网会话在本阶段接入。
本阶段之前不要求用户连接 PS 网口，不修改主机网卡，也不因网络未验收阻塞独立模块编写/仿真。

### 建议文件

- `src/ps/src/net_control.c`
- `src/ps/src/video_packet.c`
- `src/ps/src/video_sender.c`
- `src/ps/src/dma_manager.c`
- `src/ps/src/session.c`

### 配置与编程任务

- 核对 PS GEM/MDIO、实际 PHY、电平、RGMII 延迟和时钟；保留板级校准入口及超时。
- 确认连接的是 PS 网口，在隔离测试网络中确认不冲突的 MAC/IP/网关及主机地址；系统网卡改动需用户确认。
- 补齐 M01/G0 的网络子项：实际链路、ping、lwIP TCP echo，再测 UDP 单向吞吐。
- 实现 TCP 控制连接、消息长度检查、超时和状态机，接入 M12 的 TCP/UDP 接收与重放窗口。
- 将 JPEG 帧切成不超过约 1400 字节的 UDP 明文片段。
- 为每个片段生成固定包头、AAD 和唯一 Nonce。
- 调用 `dma_crypto` 和 AES-GCM IP 生成密文与 Tag。
- 发送时避免复制，条件允许时使用 lwIP zero-copy pbuf。
- 建立统计项：帧数、包数、字节数、丢帧、DMA 错误、GCM 错误和发送失败。

### 调试顺序

1. PS 网口配置、链路、ping/echo 与 UDP 吞吐；补齐完整 G0。
2. 固定测试数据，明文 UDP 发送。
3. 固定 JPEG 文件，主机重组并显示。
4. 摄像头 JPEG，明文实时显示（G4）。
5. 固定 Key/Nonce，插入 AES-GCM（G5）。
6. 最后接入 ML-KEM 会话密钥和真实 TCP 握手（G6）。
7. 长期、拔网线、会话重建和异常恢复测试（G7），最后整理交付材料。

### 完成判据

- 明文阶段连续发送 30 分钟，帧边界和长度正确。
- 加密阶段每包 Nonce 唯一，Tag 全部可验证。
- 网络阻塞时采用明确的整帧丢弃策略，不覆盖 DMA 正在使用的缓冲区。
- G0 全部子项与 G4～G7 实际通过后，才宣称联网整机验收完成；M15 文档整理不替代实测。
