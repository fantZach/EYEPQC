# EYEPQC v1 协议（M00）

第一版固定 ML-KEM-512、AES-128-GCM、12 字节 Nonce、16 字节 Tag，版本号 1，套件号 1。
所有多字节整数采用网络字节序（big-endian），无符号。以下格式是线上的字节格式；
C 结构体仅供内存使用，禁止强制转换、直接发送结构体或依赖主机对齐。

2026-10-12 三端扩展保持本协议字节格式不变。文中的 USB“主机”为 PC；目标模式的密码会话对端为移动端，
PC/可选中转负责原样双向转发控制和单向转发视频，具体部署及队列约束见 [三端架构](architecture.md)。
以下“主机预置公钥/执行 Encaps/验 Tag”等密码职责在新模式中由移动端承担；现有 PC 解密仍是调试基线。

## USB CDC 流封装

PS USB0 从机与主机建立一个双向 CDC ACM 字节流。每条记录使用
`channel:u8 || record_length:u16_be || record`：通道 1 为控制消息（双向），
通道 2 为视频分片（仅板卡到主机）；记录长度上限分别为 1036 和 1456 字节。
先检查通道与长度再读取或分配，读到 EOF、超时半包或非法长度时关闭端口并重新握手，
不得沿用旧会话密钥。USB 不保留应用记录边界，接收器必须处理拆包和粘包。
外层封装只负责分帧，视频的 40 字节包头仍作为 AES-GCM AAD；
控制消息保留自己的长度与 MAC 检查。`COM` 号不固定，主机按设备标识发现。

## 视频分片（通道 2）

`40-byte header || payload || tag`。加密时 payload 是密文，完整包头原始字节是 AAD。
明文调试模式 flags=0，无 Tag，必须显式启用；会话进入加密模式后禁止降级。

| 偏移 | 字段 | 字节 | 约束 |
|---:|---|---:|---|
| 0 | version | 1 | 1 |
| 1 | flags | 1 | 0=明文调试，1=加密，其他拒绝 |
| 2 | header_length | 2 | 40 |
| 4 | session_id | 4 | 会话标识，不替代密钥或 Nonce |
| 8 | frame_id | 4 | 会话内递增；回绕前重协商 |
| 12 | packet_id | 2 | 从 0 开始，小于 packet_count |
| 14 | packet_count | 2 | ceil(jpeg_length / 1400) |
| 16 | jpeg_length | 4 | 4～2,097,152 |
| 20 | payload_length | 2 | 1～1400，符合该分片的精确长度 |
| 22 | reserved | 2 | 0 |
| 24 | timestamp | 8 | 从会话开始计的单调微秒时间；同帧相同 |
| 32 | packet_sequence | 8 | 会话内全局递增，跨帧连续 |

除末片外每片明文均为 1400 字节，末片为余数（整除时仍为 1400）。
1400 字节分片上限沿用现有 PL 加密与主机黄金参考，不是 USB MTU 限制；
加密记录最大为 `40 + 1400 + 16 = 1456` 字节。
超出上限、字段不一致、截断、尾随数据必须拒绝，先检查长度再分配帧缓冲。
空明文用于 AES-GCM 算法测试，不能作为 JPEG 分片发送。

Nonce 为 `uint32_be(session_epoch) || uint64_be(packet_sequence)`，共 12 字节。
sequence 从 0 开始，每个被分配的序号只用一次，即使发送失败也不回收；不得回绕。
session_epoch 来自握手派生的 nonce_prefix。每次握手必须使用新共享秘密和双方新随机数，
不能仅更换 32 位前缀来保证旧密钥下的唯一性。M10 必须实施限额、重协商与旧密钥清零。

解密接口认证失败抛出 InvalidTag，不返回明文。字段格式通过不代表认证通过；
认证成功后才可更新重放窗口、会话状态或 JPEG 组帧缓冲。
同帧的 session_id、frame_id、jpeg_length、packet_count、timestamp 必须一致。
重放、组帧、JPEG 标记和显示在 M10/M12 实现；M00 仅提供格式和密码参考。
timestamp 不是双方同步的墙钟，未经时钟同步不得将其直接用作端到端延迟。

## 控制消息（通道 1）

12 字节前缀：`magic[4]='EYPQ' || version:u8 || type:u8 || reserved:u16=0 || body_length:u32`。
先解析前缀并检查 body_length≤1024，再读取 body；每种消息还必须满足下表长度。
USB CDC 不保留应用消息边界，ControlDecoder 继续处理控制消息的拆包/粘包；
外层记录长度必须与内部控制前缀的 body_length 一致，协议错误后关闭端口。

| type | 消息 | body 字节 | body 格式 |
|---:|---|---:|---|
| 1 | HELLO | 36 | min_version:u8, max_version:u8, suite:u16, host_random[32] |
| 2 | HELLO_ACK | 36 | version:u8=1, version:u8=1, suite:u16=1, board_random[32] |
| 3 | KEM_CIPHERTEXT | 768 | FIPS 203 ML-KEM-512 密文 |
| 4 | FINISHED_BOARD | 32 | HMAC-SHA256(control_key, `board finished` || transcript_hash) |
| 5 | FINISHED_HOST | 32 | HMAC-SHA256(control_key, `host finished` || transcript_hash) |
| 6 | START | 40 | control_sequence:u64, MAC[32] |
| 7 | STOP | 40 | control_sequence:u64, MAC[32] |
| 8 | REKEY | 40 | control_sequence:u64, MAC[32] |
| 9 | ERROR | 2～258 | code:u16, UTF-8 文本[0～256] |

握手顺序为 HELLO → HELLO_ACK → KEM_CIPHERTEXT → FINISHED_BOARD → FINISHED_HOST → START。
公钥为主机预置、固定验证的板卡静态 ML-KEM-512 公钥（800 字节），私钥为 1632 字节，
共享秘密为 32 字节；公钥不由不可信 USB 消息替换。

M10 的派生约定：transcript_hash = SHA256(`EYEPQC v1` || SHA256(固定公钥) ||
完整 HELLO || 完整 HELLO_ACK || 完整 KEM_CIPHERTEXT)，完整消息均包括前缀。
HKDF-SHA256 使用共享秘密作为 IKM、transcript_hash 为 salt，info 为 ASCII `EYEPQC v1 keys`，
输出 56 字节，依次为 video_key[16]、control_key[32]、nonce_prefix[4]、session_id[4]。
后二者按网络字节序解释。

命令 MAC = HMAC-SHA256(control_key, `host command` || transcript_hash ||
完整命令前缀 || control_sequence:u64)。命令序号从 0 递增，重复或回绕拒绝。
Finished 使用恒定时间比较并只在对应握手状态验证；在双向 Finished 完成前不发送视频。
ERROR 只用于诊断，无认证，不触发控制状态变化；已建立会话的错误恢复通过已认证命令或断连进行。
套件匹配、Finished、MAC、超时、状态机、KDF 和重放窗口在 M10/M11 实现。

错误码固定为：1 VERSION、2 LENGTH、3 STATE、4 KEM、5 AUTH、6 BUSY、7 INTERNAL。
禁止将私钥、共享秘密和派生密钥写入错误文本。v1 尚不提供主机身份认证。

## 黄金参考与测试数据

账号新链路使用 suite 2：固定身份 bootstrap 后认证临时 ML-KEM，重新 Finished 后才能 START。
type10/11 长度、MAC 域、business transcript 和明确降级拒绝见
[临时 KEM 冻结契约](account_ephemeral_protocol.md)。原 suite1 只作显式开发兼容。
本节扩展正在实现，不改变已有历史 suite1 的实测范围。

`pc/src/host/crypto_ref.py` 使用 cryptography==48.0.0 的 AESGCM，
独立 GF(2^128)/GHASH 模型输出 H、J0、输入块和每块累加值。
GHASH 使用 SP 800-38D 的 MSB-first 位序、约简常量 e1 || 0^120；
AAD 与密文分别补零，末块为两个 64 位 big-endian 比特长度。
后续 RTL 的 128 位总线中第一个线缆字节对应 bits[127:120]。

AAD 算法参考上限 64 字节（线上始终 40），明文上限 1400 字节。
向量包含长度 0、1、15、16、17、31、32、1400，AAD 边界与固定 SHAKE256 派生随机样本，
以及 Key、Nonce、AAD、密文、Tag 单比特篡改。SHAKE256 确定性输入仅用于可复现测试。

ML-KEM 黄金参考使用 kyber-py==1.2.0（MIT 或 Apache-2.0，选 MIT），
只用于离线、FIPS 203/ACVP 比对。该教育实现非恒定时间，不可作为在线握手或 PS 密码实现。
M09 必须另选、锁定并验证可移植 C 实现。所有已提交的测试私钥和种子都是公开测试数据。

来源：[NIST GCM/CAVP](https://csrc.nist.gov/projects/cryptographic-algorithm-validation-program/cavp-testing-block-cipher-modes)、
[NIST ACVP v1.1.0.35](https://github.com/usnistgov/ACVP-Server/tree/v1.1.0.35/gen-val/json-files)、
[kyber-py](https://github.com/GiacomoPope/kyber-py)。标准测试向量保存在 data/kat，
生成向量保存在 sim/vectors，SHA-256 清单用于后续硬件比对。
