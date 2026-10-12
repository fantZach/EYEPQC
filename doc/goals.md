# EYEPQC 单向 JPEG 视频加密监控系统

2026-10-12 更新：项目划分为开发板、PC、移动端三个子项目，目标链路见 [三端架构](architecture.md)。
板卡到 PC 解密保留为开发基线；PC 密文桥和 Android 接收端已进入软件互操作验证，可选远程中转待实现。

## 1. 项目综述

- 硬件平台：正点原子领航者 Zynq-7020 开发板，主控器件为 XC7Z020。
- 终端平台：Windows PC；Android 原生 Java 应用（最低 API 26），OkHttp 4.12.0 / Bouncy Castle 1.81。
- 视频输入：ATK-MC5640 V2（OV5640）摄像头，通过领航者的 OLED/摄像头接口连接，使用摄像头内部 JPEG 压缩功能。
- 密钥协商：使用 ML-KEM 完成握手并建立共享秘密，不采用传统公钥算法组成混合 KEM。
- 视频保护：使用 AES-GCM 对视频数据进行加密和完整性认证。
- 传输方向：视频从 Zynq 经 USB、PC 和可选远程中转单向发往移动端；握手、确认和重新协商等控制消息允许双向传输。
- 系统架构：PS 端负责协议、PS USB0 从机、DMA 和硬件调度，PL 端负责摄像头采集及密码运算。
- 应用目标：采集 JPEG 帧，经 AES-GCM 加密后通过 USB Slave 交给 PC 转发，由移动端完成认证、解密、JPEG 解码和显示；先完成局域网单观看端 MVP，录像后续安排。
- PC 角色：保留本地解密调试工具，新增独立纯转发模式；可选公网中转服务归 PC 子项目维护。
- 部署顺序：先 PC 与手机同一局域网，不需要租服务器；需要异地观看时再接入可选公网中转。

## 2. 推荐技术路线

第一版建议采用以下配置：

- ML-KEM-512：资源需求较低，适合作为 XC7Z020 上的首个可运行版本。
- AES-128-GCM：与 ML-KEM-512 的整体安全级别匹配，同时提供机密性与完整性保护。
- JPEG：直接使用 ATK-MC5640 V2 内部生成的压缩帧，不在 Zynq 中实现 H.264 或 JPEG 编码器。
- USB CDC ACM：第一版使用板载 PS USB0 从机，在主机上呈现串口；同一双向字节流承载少量控制消息和单向加密视频。量产时须申请正式 USB VID/PID，测试固件的标识不得直接沿用。
- 流封装：保留已验证的控制消息和 1400 字节 JPEG 分片/AES-GCM AAD 格式；外层增加通道号和长度，不依赖 TCP/UDP/IP。
- AXI DMA：负责变长 JPEG 码流、DDR 与 PL 密码模块之间的数据搬运。JPEG 不是固定行宽的原始视频，因此不使用 AXI VDMA 作为 JPEG 码流 DMA。
- PS USB0：使用领航者 CF7020B 的 USB Slave Type-C、USB3320 PHY（MIO28～39，复位 MIO9）；PS GEM 仅作为可选后续传输方案。
- PS 软件环境：第一版使用 Vitis Standalone（裸机）和 AMD `usbps` 驱动，不安装 PetaLinux。若后续需要复杂驱动或多进程服务，再评估迁移到 PetaLinux。

ML-KEM 的实现以 NIST FIPS 203 为准，不使用旧版 CRYSTALS-Kyber 接口作为最终规范。AES-GCM 的设计以 NIST SP 800-38D 为准。

## 3. 系统划分

### 3.1 PS 端

- ML-KEM 握手状态机与会话管理。
- 基于 PS USB0 CDC ACM 的双向控制/单向视频字节流。
- AXI DMA 配置、中断、缓存一致性及 DDR 双缓冲管理。
- JPEG 帧长度管理、分包、发送和主机控制消息处理。
- 通过 SCCB 控制器配置 OV5640 的 JPEG 输出模式、分辨率、帧率与图像质量。
- 密钥派生、会话编号、序列号和重放窗口管理。
- 性能、错误和丢包统计。

### 3.2 PL 端

- ATK-MC5640 V2 的 DVP 数据采集：`PCLK`、`VSYNC`、`HREF` 和 `D[7:0]`。
- JPEG 帧边界检测、`FF D8`/`FF D9` 标记校验和字节计数。
- 摄像头 PCLK 域到 AXI 时钟域的异步 FIFO。
- AES-GCM 单向加密数据通路；板端不实现 AES-GCM 解密模块。
- AXI4-Stream 数据接口和 AXI4-Lite 控制接口。
- 密钥、Nonce、AAD、认证标签和状态寄存器。
- 后续逐步加入 ML-KEM 加速模块：
  1. Keccak/SHA3/SHAKE；
  2. NTT、模乘和多项式运算；
  3. 根据资源情况集成完整 ML-KEM 控制器。

### 3.3 推荐数据流

```text
ATK-MC5640 V2
  | JPEG / PCLK / VSYNC / HREF / D[7:0]
  v
PL：JPEG 采集与异步 FIFO
  | AXI4-Stream + AXI DMA S2MM
  v
DDR：JPEG 明文帧缓冲
  | AXI DMA MM2S
  v
PL：AES-GCM Encrypt（ML-KEM 目前为 PS 软件，独立 PL 加速实验另行验收）
  | AXI DMA S2MM
  v
DDR：密文包缓冲
  | PS USB0 CDC ACM
  v
PC：密文双向转发（控制双向，视频向移动端）
  | 局域网 / 可选公网中转服务
  v
移动端：认证解密 -> JPEG 解码 -> 显示
```

### 3.4 三子项目职责

- `board/`：PL/PS 源码、第三方密码库、板级约束及构建/板测脚本。
- `pc/`：现有 Python 调试端及后续 USB/网络桥；公网中转服务属于同一项目但独立部署。
- `mobile/`：Android 终端公钥 pin、ML-KEM 封装、会话管理、认证解密及播放；调试 APK 构建通过，真机验收待做。
- `doc/`、`sim/`、`data/kat/`、`report/`：共享协议、跨端测试、标准向量及证据，不复制到三个项目。

## 4. 分阶段目标

### 阶段 0：软件基线与黄金参考

目标：先在主机或 PS 软件环境中验证算法与协议，建立后续硬件比对基线。

任务：

- 实现或移植符合 FIPS 203 的 ML-KEM-512。
- 实现 AES-GCM 软件参考模型。
- 使用标准测试向量验证 ML-KEM 和 AES-GCM。
- 定义握手消息、视频包头、错误码和状态机。
- 定义密钥派生和会话密钥更新方法。
- 生成硬件仿真所需的输入、期望输出和随机测试数据。

验收标准：

- ML-KEM 双方得到完全一致的 256 位共享秘密。
- AES-GCM 加解密结果与软件黄金参考一致。
- 修改密文、AAD 或认证标签后，解密必须失败。
- 不同长度及非 16 字节对齐的数据均能正确处理。

### 阶段 1：JPEG 采集与本地加密验证

目标：在领航者 Zynq-7020 上完成摄像头 JPEG 采集和 PL 加密，并用软件参考模型验证结果。板端只实现 AES-GCM 加密数据通路，不放置硬件解密核。

推荐流程：

```text
ATK-MC5640 V2 JPEG 输出
  -> PL JPEG 采集与异步 FIFO
  -> AXI DMA S2MM
  -> DDR JPEG 明文帧
  -> AXI DMA
  -> PL AES-GCM 加密
  -> DDR 密文与认证标签
  -> PS/主机软件解密
  -> 与原始 JPEG 逐字节比对
```

任务：

- 先用固定 JPEG 文件验证 AES-GCM，再接入 ATK-MC5640 V2 实时数据。
- 完成 OV5640 SCCB 初始化，将摄像头配置为 JPEG 输出模式。
- 完成 `PCLK`、`VSYNC`、`HREF` 和 `D[7:0]` 采集逻辑。
- 结合物理帧同步信号与 `FF D8`/`FF D9` 标记确认 JPEG 帧完整性。
- 完成异步 FIFO、AXI DMA、DDR 双缓冲、缓存一致性和中断处理。
- 完成 AES-GCM Encrypt RTL/HLS 核及 AXI 接口。
- 支持 AAD、96 位 Nonce 和 128 位认证标签。
- 支持密钥装载、复位、错误报告和密钥清零。
- 记录 JPEG 实际帧长、帧率、加密吞吐率、延迟、最高频率和资源占用。

验收标准：

- 采集得到的每个 JPEG 文件具有有效的 `FF D8` 和 `FF D9` 标记，并能在主机正常解码。
- 原始 JPEG 与软件解密恢复的 JPEG 逐字节一致。
- 随机翻转密文、AAD 或认证标签中的任意位后，软件解密端拒绝输出。
- 连续采集和加密多帧无 FIFO 溢出、DMA 卡死、丢字节或帧长度错误。
- 完成综合和实现，时序收敛且无严重告警。
- AES-GCM 吞吐率高于摄像头实际 JPEG 码率，并预留不少于 20% 的余量。

### 阶段 2：板卡到 PC 的 USB 开发基线

目标：主机与 Zynq 通过 USB Slave 完成 ML-KEM 握手，随后由 Zynq 单向发送经过 AES-GCM 保护的 JPEG 视频流。

任务：

- USB 控制通道完成协议版本协商、ML-KEM 握手和密钥确认。
- 通过 KDF 从 ML-KEM 共享秘密派生视频密钥、控制密钥和 Nonce 基值。
- USB 视频通道传输加密 JPEG 分片；两类消息在同一字节流中按通道号与长度分帧。
- 主机完成接收、认证、解密、JPEG 帧重组、解码、显示和录像。
- 实现序列号、丢帧/传输错误统计和重放检测；字节流解析错误时关闭端口并重建会话。
- 支持重新握手和会话密钥更新。

已验证的视频分片结构：

```text
version | session_id | frame_id | packet_id |
packet_count | jpeg_length | payload_length | timestamp |
ciphertext | gcm_tag
```

包头应作为 GCM 的 AAD 参与认证。单片载荷上限沿用已验证的 1400 字节，便于复用 G3 的 PL 加密及主机解密链路；USB 不受以太网 MTU 限制。

Nonce 建议由会话标识与单调递增的包序列号构成：

```text
session_epoch || packet_sequence
```

同一个 AES 密钥下不得重复使用 Nonce。

验收标准：

- 主机和板卡可以稳定完成握手及密钥确认。
- 主机能够实时认证、重组、解密并显示 JPEG 视频。
- 视频分片被篡改时不会输出未认证的视频数据。
- 任一分片缺失或认证失败时丢弃对应 JPEG 帧，下一完整帧能够自动恢复显示。
- 能正确统计传输/解析错误、认证失败、丢帧和会话重置。
- 连续运行测试期间无崩溃、DMA 卡死或密钥错乱。

### 阶段 2B：PC 转发与移动端解密（新增，待实现）

- 先实现单板、单观看端的局域网双向记录转发，复用现有 USB/视频/控制格式。
- 将终端握手和验 Tag/解密移植到移动端，PC 与可选中转服务不参与业务密钥派生。
- 实现接入授权、固定板卡公钥验证、有界队列、断线清理和新会话重建。
- 在手机上验证标准向量、篡改拒绝、反重放、完整 JPEG 显示及长时间连接；局域网通过后按需接公网。
- 以手机认证解码显示处的实测帧率检验 45 fps 目标，同时记录网络码率、延迟和丢帧，不能复用 PC/板端吞吐作为手机结果。

完成判据和 G8/G9 新门禁见 [steps 第 22 节](steps.md#22-三端扩展pc-转发与移动端解密)。
原有 G0/G7 故障与冷启动子项保持待验，网络扩展不改变历史结论。

### 阶段 3：竞赛优化与交付

目标：在已跑通的系统上完成硬件加速、量化对比和可复现交付。

任务：

- 以 PS 软件 ML-KEM 为基线，逐步加入 PL 加速模块。
- 对比优化前后的握手延迟、吞吐率、资源和功耗。
- 优化 JPEG 采集、AES-GCM、DMA、DDR 和 PS USB0 数据通路。
- 对比不同 USB 分片/缓冲策略、JPEG 质量、分辨率和帧率下的系统表现。
- 整理源码、仿真、上板脚本、实测数据和设计报告。
- 保存大模型协作记录和自我纠错过程。
- 在 `skill/` 目录中形成可供其他 FPGA 项目复用的技能包。

## 5. JPEG 视频规格与缓冲建议

ATK-MC5640 V2 输出的是一系列彼此独立的 JPEG 图片，系统将其组织成连续的 MJPEG 风格视频流，但不额外封装为 H.264。

开发顺序建议：

1. 640 x 480，15 fps，中等 JPEG 质量；
2. 640 x 480，30 fps；
3. 1280 x 720，逐步测试可稳定达到的帧率与 JPEG 质量；
4. 在带宽、DDR 和时序允许时，再测试更高分辨率。

JPEG 为变长编码，USB 有效载荷码率按实测值计算：

```text
码率 = 平均 JPEG 帧大小（字节）x 帧率 x 8
```

DDR 缓冲区必须根据实测最大帧长而不是平均帧长分配，并保留溢出检测。建议至少使用两个 JPEG 帧缓冲区，使采集与加密/发送可以并行进行。

## 6. 握手和身份认证建议

ML-KEM 用于建立共享秘密，但不会自动证明通信对端身份。第一版可以采用以下方案：

1. 板卡预置静态 ML-KEM 私钥。
2. 接收终端预置并校验板卡 ML-KEM 公钥；开发基线为 PC，目标模式为移动端。
3. 接收终端执行 Encaps，并通过 PC/可选中转将 KEM 密文发送给板卡。
4. 板卡执行 Decaps，双方得到共享秘密。
5. 板卡发送由派生控制密钥保护的 `Finished` 消息。
6. 接收终端验证成功并完成双向 Finished 后，发送认证 START，才开始传输视频。

该方案完成接收终端对板卡的单向身份确认，未提供板端对观看者的身份认证；网络接入服务须另做设备/用户授权。
控制消息必须端到端双向转发，不能仅转发视频。开发态 PC/JTAG 装载测试私钥，因此 PC 仍属于可信调试环境，
不能据此宣称对不可信 PC 的生产级端到端保密。

## 7. 关键安全要求

- ML-KEM KeyGen 和 Encaps 必须使用可靠随机数源。
- 每个 AES-GCM 密钥下的 Nonce 必须唯一。
- 密文认证失败时不得输出对应明文。
- 会话结束或重新握手后，应清除旧密钥和敏感中间值。
- 包头、协议版本、帧号和包序号应作为 AAD 参与认证。
- 接收端应实现重放检测，并限制可接受的序列号窗口。
- 板卡上的长期私钥保存方式和侧信道防护应在报告中说明其安全边界。

## 8. 待实验确认的事项

- 领航者开发板及 ATK-MC5640 V2 的具体硬件版本、P2 接口引脚和约束文件。
- OV5640 在 640 x 480 和 1280 x 720 下可稳定达到的 JPEG 帧率、平均帧长和最大帧长。
- SCCB 配置使用 PS I2C/EMIO、AXI IIC，还是复用正点原子 PL 初始化例程。
- 裸机 USB CDC 在完整相机→AES-GCM→主机链路下的持续吞吐、CPU 占用和缓存一致性表现。2026-09-29 的独立 USB0 30 秒合成码流验证达到 16.37 MB/s、30016 个连续 16 KiB 块全量校验通过；不替代端到端视频验收。
- USB 流封装、缓冲满时整帧丢弃策略和主机显示缓存深度。
- ML-KEM 最终仅加速热点，还是完整算法都在 PL 中实现。
- 是否需要处理主动中间人攻击及双向身份认证。

## 9. 参考资料

- [NIST FIPS 203 - Module-Lattice-Based Key-Encapsulation Mechanism Standard](https://csrc.nist.gov/pubs/fips/203/final)
- [NIST SP 800-38D - GCM and GMAC](https://csrc.nist.gov/pubs/sp/800/38/d/final)
- [AMD Zynq-7000 SoC Data Sheet: Overview (DS190)](https://www.amd.com/content/dam/xilinx/support/documents/data_sheets/ds190-Zynq-7000-Overview.pdf)
- [AMD AXI DMA Product Guide (PG021)](https://docs.amd.com/r/en-US/pg021_axi_dma)
- [正点原子领航者 ZYNQ 开发板](https://www.alientek.com/Product_Details_17/38.html)
- [正点原子 OV5640 摄像头格式与使用说明](https://wiki.alientek.com/docs/Boards/Linux/IMX6U/I.MX6U%20%E5%BF%AB%E9%80%9F%E4%BD%93%E9%AA%8B%E6%89%8B%E5%86%8C/function%20test/ov5640_test/)
