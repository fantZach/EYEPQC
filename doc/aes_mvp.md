# 固定图片 AES-GCM MVP

按 2026-09-27 用户要求提前执行 `steps.md` 第 5.1 节，不等待 PS 网口或摄像头。
MVP 独立验收，不将 M01/G0、M07/M08 全 PL 或完整视频链路标为通过。

## 实现

主机图片 → JTAG 写入 ELF 自有 DDR mailbox → PS 经 GP0/AXI4-Lite 调用 PL AES-128
→ PS GHASH 生成 128-bit Tag → JTAG 回读 → 主机认证解密、全部字节和 SHA-256 比对。

AES 使用 [secworks/aes](https://github.com/secworks/aes)，固定提交
`80dc4718e1dcbbdb4b0dd1bdb393d8f7b98981dc`。六份上游 RTL 原样保留，
BSD-2-Clause 许可证在 `src/rtl/crypto/secworks_aes/LICENSE`，版权头不移除。
本地接口固定 AES-128 Encrypt，解密由主机负责；不自行实现 AES 算法。

- `src/rtl/crypto/aes_axi_lite.sv`：独立 AW/W，单笔事务，背压与非法访问响应；
  busy 时拒写，允许 ZEROIZE 中止操作，零化上游轮密钥与状态。
- `src/ps/src/aes_image_mvp.c`：512 KiB 自有 DDR 自检、有界 AES 轮询、异常处理、密钥零化。
- `src/ps/src/mvp_gcm.c`：可移植 GHASH/GCM；96-bit Nonce、完整 Tag、尾块与 AAD。
- `src/host/aes_image_mvp.py`：新随机 key/nonce、构建哈希检查、原生 XSDB 传输、独立认证比对。

PL 时钟 100 MHz，AES 地址 `0x43c00000`；32-bit 寄存器按高字在先传递 AES 字节。
`0x00` CTRL：1=初始化密钥、2=加密块、4=零化；`0x04` STATUS：bit0 busy、bit1 key-ready、
bit2 result-valid；`0x08` ID=`0x41455331`；`0x10..1c` KEY、`0x20..2c` INPUT 写入；
`0x30..3c` OUTPUT 只读。Key/Input 不可读，非法地址/忙时写入返回 SLVERR。

DDR mailbox 共 524364 字节，64-byte 对齐；地址从实际 ELF 的 `mvp_job` 符号提取，
不硬编码任意 DDR scratch。头四个小端 u32 为 magic/state/status/length，随后
key16、nonce12、AAD16、data524288、tag16。state 0=就绪、1=请求、2=成功、3=失败。
JTAG 完整写入后才发布请求；空闲/传输时 DCache 关闭，PS 独占处理期间启用缓存。
PS 完成并清理密钥后 flush/disable 缓存，再发布结果；异常也先刷新清理结果。
JTAG 处理期间只能读取未变化的 state，不读写正在由 PS 处理的图片/密钥。

## 复现

在仓库根目录、已有 `.venv` 和 `requirements.txt` 环境中执行：

```powershell
& ./.venv/Scripts/python.exe sim/tb/test_aes_mvp.py
& ./prj/build_aes_mvp.ps1 -BuildName aes_mvp_demo
& ./prj/capture_uart.ps1 -Port COM4 -Seconds 60
```

串口捕获运行期间，在另一个终端执行（COM4 仅用于日志，图片传输走 JTAG）：

```powershell
& ./.venv/Scripts/python.exe src/host/aes_image_mvp.py --workspace build/vitis/aes_mvp_demo
# 自选图片：在脚本后加文件路径，PNG/JPEG 均按原始文件字节处理。
& ./.venv/Scripts/python.exe src/host/aes_image_mvp.py 'D:/pictures/test.jpg' --workspace build/vitis/aes_mvp_demo
```

工具默认位于 `D:/AmdDesignTools/2026.1`；构建使用 `-ToolRoot`，主机使用 `--tool-root` 修改。
构建必须使用新的 BuildName，不覆盖旧产物；主机输出同样要求新目录。
当前硬件仍为 `build/vivado/aes_mvp_2`；优化版软件为 `build/vitis/aes_mvp_o3_word_1`，
使用 `--workspace build/vitis/aes_mvp_o3_word_1`。旧 ELF/源码哈希不匹配时脚本拒绝下载，禁止混用。
默认图片为标准库生成的 64×64 RGB PNG，不下载素材、不需要图像库。

主机先校验源码、XSA、ELF、bit、PS init 哈希及 XSA 内部条目，才访问板卡。
下载会复位 PS、临时配置 PL、装载同平台 ELF；不会写入 SD/QSPI/Flash。
XSDB 的 Windows batch 退出码不能独立作为成功依据，必须出现 `AES_MVP_JTAG_OK`
并实际通过认证比对。出现 `AES_IMAGE_MVP_PASS` 才算此图片成功。

## 本地输出

默认输出 `data/captures/aes_mvp_<时间戳>/`（Git 忽略）：

- `original.png/jpg`、`restored.png/jpg`：原图及认证成功后还原图片。
- `image.aesgcm`：AAD16 || nonce12 || ciphertext（原图字节数）|| tag16。
- `key.bin`：16-byte 本地演示密钥，勿分享或提交；Windows 权限继承所在目录 ACL。
- `result.json`：长度、原图/还原 SHA-256、Tag、Nonce、构建哈希、篡改拒绝结果。
- `jtag.log`：原生下载/传输日志，不包含密钥。

AAD 为网络字节序 `MVP1 || version(u32=1) || image_length(u32) || reserved(u32=0)`。
文件可用已有库恢复：`AESGCM(key).decrypt(blob[16:28], blob[28:], blob[:16])`；
必须先验证 Tag，失败时不能显示或写出未经认证的图片。
此格式只用于离线 MVP，不替代 M00 网络协议、会话与重放管理。

## 验证状态

离线：实际上游 AES RTL + AXI 接口通过 NIST AES-128 与 12 个随机块，
覆盖通道错开、B/R 背压、WSTRB、忙时拒写、非法地址、复位/零化。
实际 C GHASH/GCM 与 80 个 M00、20 个 NIST、5 个长输入向量逐字节一致，
包含 65535/65536 及 524287/524288 字节边界；AES 故障清理、超长拒绝及主机认证边界通过。

首次硬件构建时序通过，但首次/断电重试均在 ARM 运行后发生 DAP 超时，未取得图片结果。
定位到共享 `proc_sys_reset` 的 `C_AUX_RESET_HIGH=0`，而辅助输入被接为 0，
导致 PL 永久复位。已显式改为辅助高有效、外部低有效，并在 BD 验证后断言极性，
新增 M01 配置回归；新硬件 `aes_mvp_2` 已构建通过并恢复 DAP/DDR 访问。
原 64 KiB 软件已实际上板通过：9373 字节 PNG 两次运行、65536 字节合法 PNG 上限一次运行，
主机独立认证解密后全部字节及 SHA-256 一致，Key/Nonce/AAD/密文/Tag 篡改均拒绝。
上限测试 UART `MVP RESULT bytes=65536 status=0 elapsed_us=12338956`（旧版处理时缓存关闭）。

按用户新提供的 365954 字节 JPG，将软件缓冲区扩至 512 KiB，复用同一 bit/XSA，
只重建独立 ELF；PS 处理期间启用缓存，JTAG 传输期间保持缓存关闭。完整原始 JPG 已实测通过，
无压缩/裁剪，原图与还原图 365954 字节全部一致，SHA-256 均为
`f7ebf2bd3af8a998c5afd155982faa576be6bc8e1babde5ec1dfb2b7f19d5650`。
Key/Nonce/AAD/密文/Tag 五类篡改均被主机拒绝，回读的板端 key/nonce 已零化。
另实际测试 524288 字节合法 PNG，认证/全部字节/SHA-256 同样通过，验证新上限。

首次 MVP 的历史实测命令与本地证据（图片、密钥和日志不提交 Git，当前优化版复测见下节）：

```powershell
& ./.venv/Scripts/python.exe src/host/aes_image_mvp.py 'D:/TEST/media/微信图片_20260910160056_203_3.jpg' --workspace build/vitis/aes_mvp_3 --output data/captures/aes_mvp_userjpg_1
```

已存在的输出不可覆盖；复测须省略 `--output` 或改用新目录。
JPG 结果在 `data/captures/aes_mvp_userjpg_1/result.json`，还原图为 `restored.jpg`；
上限结果在 `data/captures/aes_mvp_boundary_512k/result.json`。
串口记录 `data/captures/aes_mvp_userjpg_uart_1.log`：

```text
MVP RESULT bytes=365954 status=0 elapsed_us=4652657
MVP RESULT bytes=524288 status=0 elapsed_us=6820005
```

时间为板端 PS/PL 混合处理的近似耗时，不含 JTAG 传输，不代表独立 AES 核或视频吞吐。
所有 18 项离线测试及 Git pre-commit hook 通过，5 份 M00 向量可复现。
原生 Vivado 2026.1 实现：100 MHz，WNS 0.767 ns / WHS 0.089 ns / WPWS 4.146 ns；
2987 LUT、3094 FF、0 BRAM/DSP，DRC 0 项。methodology 保留 LUT 异步复位和 LED
外部 output-delay 提示，不宣称侧信道/故障防护或 LED 实测通过。

对应产物 SHA-256：

| 产物 | SHA-256 |
|---|---|
| `build/vivado/aes_mvp_2/m01.xsa` | `ff7a54bbc0116e407912ac0a819fad119b2628c271feda6b4bc93cab69d64e18` |
| `aes_mvp_3/aes_mvp/build/aes_mvp.elf` | `c3094ccad7159afa81ab1b9f249abc6cf322003d642267b672c62c6baf64211e` |
| `aes_mvp_3/aes_mvp/_ide/bitstream/m01.bit` | `c3afe0fc8d60394b0bc99350752fe7bcfbb7c43d5c69905be474486af5a26355` |
| `aes_mvp_3/aes_mvp/_ide/psinit/ps7_init.tcl` | `19e665272199142a9c3c26c7c20ad453173c46ffcb2f839a80636f97a4dd59e5` |

软件产物路径均相对于 `build/vitis/`。构建清单的 `board_validated=false` 仅表示构建本身
不验板；具体图片验证清单的 `board_validated=true` 才表示该次实际图片往返通过。

## 性能优化（2026-09-27）

只修改软件，保持 AES 核、bit/XSA、输入 JPG、Mailbox ABI、GCM/AAD/Tag 和密钥零化不变：

1. Vitis 应用显式启用 `-O2`，并检查实际编译命令，构建清单记录优化级别与构建脚本哈希。
2. GHASH 从 16-byte 数组操作改为 4 个 `uint32_t`，仍为固定 128 次乘法循环，
   显式大端装载/输出；没有未对齐整数强转、秘密索引表或按秘密值分支。
3. UART 增加 AES 调用次数和累计 AES/MMIO 时间，其余时间包含 GHASH、CTR/XOR、
   密钥初始化及计时开销，标为 `ps_other_us`，不能当作纯 GHASH 测量。

同一张 365954 字节 JPG（SHA-256 与上文一致），同一 100 MHz 硬件，测量窗口均为
缓存启用后的板端处理，截止于最终缓存 flush 之前；不含启动、DDR 自检、JTAG 和主机处理。
优化版计时探针自身开销包含在总时间中，旧 `-O0` 基线没有分项探针；不是视频端到端延迟。

| 实现 | 板端处理 | AES/MMIO | PS 其余 |
|---|---:|---:|---:|
| 首次 MVP：`-O0`、byte GHASH | 4652657 us | 未分项 | 未分项 |
| `-O2`、byte GHASH | 512107 us | 50626 us | 461480 us |
| `-O2`、32-bit GHASH（首次） | 239584 us | 51039 us | 188544 us |
| `-O3`、同一 32-bit GHASH（三次中位数） | 153437 us | 49984 us | 103453 us |

第一轮 `-O2` 版同图三次处理分别为 239584 / 239072 / 239584 us，中位数 239584 us，
约为原版的 19.42 倍速度，板端处理吞吐约 12.22 Mbps，同等大小约 4.17 张/秒。
仍未达到这张大图的 15 fps，不宣称摄像头/网络或持续视频验收通过。
512 KiB 上限同样通过，板端 342481 us（AES/MMIO 73163 us、PS 其余 269317 us）。
四次均通过独立主机 AES-GCM 认证、密文/Tag 比对、原图/还原逐字节和 SHA-256 比对、
五类篡改拒绝与板端 key/nonce 清理检查。
原图未压缩、裁剪或修改，三次使用新随机密钥与 Nonce。
离线 105 组 C/GCM 黄金向量全部通过，额外验证已加密首块后 AES 故障时整个数据/Tag 清零。

证据：`data/captures/aes_mvp_word_profile_uart_1.log`、
`aes_mvp_word_jpg_1/`、`aes_mvp_word_jpg_2/`、`aes_mvp_word_jpg_3/`、
`aes_mvp_word_boundary_1/`；仅日志/指标供性能分析，不输出密钥到终端或 Git。
中间 `-O2`/byte 测量日志为 `aes_mvp_o2_profile_uart_1.log`，结果为 `aes_mvp_o2_jpg_1/`。

当前优化版复测：在另一终端先运行 `capture_uart.ps1`，再执行：

```powershell
& ./.venv/Scripts/python.exe src/host/aes_image_mvp.py 'D:/TEST/media/微信图片_20260910160056_203_3.jpg' --workspace build/vitis/aes_mvp_o3_word_1
```

新机器可直接按前文完整构建；本次复用已验证 XSA，只重建了软件，原生 Vitis 命令为：

```powershell
$env:EYEPQC_MVP_XSA = (Resolve-Path build/vivado/aes_mvp_2/m01.xsa).Path
$env:EYEPQC_MVP_VITIS = Join-Path (Get-Location).Path 'build/vitis/aes_mvp_optimized_new'
$env:EYEPQC_TOOL_ROOT = 'D:/AmdDesignTools/2026.1'
& 'D:/AmdDesignTools/2026.1/Vitis/bin/vitis.bat' -s prj/build_aes_mvp.py
```

须使用全新软件目录，并检查 `AES_MVP_ELF_OK` 和新 `build_manifest.json`，不能只相信 batch 退出码。
第一轮 `-O2` ELF SHA-256 为 `0576c34a2d10fec967018a2420b514fb72deb8cae0e51ede52969f4b78d18204`，
bit/XSA/PS init 哈希与前文相同；不下载非易失镜像，不提交图片或密钥。

### 第二轮：编译器展开固定循环

仅将应用及离线 C 黄金向量检查的优化级别改为 `-O3`，PS C/RTL/协议源码不变。
原生构建核对两个 C 文件实际编译命令及清单为 `-O3`；ARM GHASH 反汇编显示
4-word 内层移位循环已展开，主乘法循环仍固定 128 次，无新增查表算法或手写汇编。
ELF 的 text 从 42781 增至 43789 字节（增加 1008），data/bss 不变。

同一原始 JPG、相同计时窗口，三次实测 153440 / 153437 / 153401 us，
中位数 153437 us：比第一轮再快 1.56 倍（耗时减少 35.96%），比最初约快 30.32 倍。
中位数对应 AES/MMIO 49984 us（22875 次调用，约 32.6%），PS 其余 103453 us（约 67.4%）。
后者包含 GHASH、CTR/XOR、初始化、清理及探针，仍非纯 GHASH 测量。
板端处理吞吐约 19.08 Mbps，同等大小约 6.52 张/秒，仍未达到 15 fps 或持续视频验收。
512 KiB 合法 PNG 上限 219779 us（AES/MMIO 71606 us、PS 其余 148172 us）。
时间转换分别取整，部分分项之和与总时间相差 1 us。

三次原图及上限四次均通过独立主机认证解密、密文/Tag/逐字节/SHA-256 比对、
五类篡改拒绝与板端 key/nonce 零化；每次使用新随机 key/nonce，不压缩或裁剪原图。
`-O3` 下 105 组离线黄金向量、AES 故障后的数据/Tag 清理及全部 18 项 hook 检查通过。
串口证据为 `data/captures/aes_mvp_o3_profile_uart_1.log`，结果为
`data/captures/aes_mvp_o3_jpg_1/`、`aes_mvp_o3_jpg_2/`、`aes_mvp_o3_jpg_3/`、
`aes_mvp_o3_boundary_1/`，均 Git 忽略。第一轮历史产物保留；其构建脚本哈希已过期，
当前源码不能直接下载旧工作区，须使用新构建或对应历史源码。

当前软件为 `build/vitis/aes_mvp_o3_word_1`；最终 ELF SHA-256 为
`c96518ff376869c1768f189a7a2e654260cfd1e9a172482d63c43a97d4548248`，
硬件/bit/PS init 哈希不变，只做易失性 JTAG 下载，不写 SD/Flash。

## 已知边界

单次最多 524288 字节；PS 软件 GHASH、逐块 MMIO 和 JTAG 是吞吐瓶颈，
视频速率需求出现后在 M07/M08 引入 PL GHASH/流接口与 M05 DMA。
没有摄像头、网络、ML-KEM 动态会话或非易失启动镜像；G0 网络/LED/30 分钟冷启动仍待验收。
每次运行使用新随机密钥/Nonce，不用固定生产密钥；演示密钥保存在本地、临时请求也包含密钥。
JTAG 可读写 RAM，开源 AES 没有侧信道掩码，异常时也不宣称清理全部处理器内部状态。
因此这是隔离开发环境中的功能演示，不是生产安全部署。
