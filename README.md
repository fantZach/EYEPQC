# EYEPQC

领航者 Zynq-7020 单向 JPEG 加密视频项目。实施顺序见 [doc/steps.md](doc/steps.md)，
目标见 [doc/goals.md](doc/goals.md)，最新进度见 [report/progress.md](report/progress.md)。

目前完成 M00 协议与离线黄金参考，已编写 M01 板级工程、自检和 echo；
构建/上板步骤见 [M01](doc/m01.md)。已解压并研究官方 7020 例程，
板级参数、JPEG 数据路径及迁移问题见 [研究记录](report/vendor_examples.md)。M01/G0 门禁尚未通过。
按用户要求，固定图片 AES-GCM MVP 已在步骤中提前并通过上板验证（完整 JPG/512 KiB PNG）；使用 GitHub 开源 AES 核，
不依赖摄像头或未连接的 PS 网口。复现与验证状态见 [图片 MVP](doc/aes_mvp.md)。
M06 开源 AES-128 核的独立判据、资源和每块周期数见 [M06](doc/m06.md)。
M07 串行 GF(2¹²⁸) 与 GHASH 的逐块验证见 [M07](doc/m07.md)；已被 M08 复用。
M08 全 PL AES-GCM AXIS 独立仿真与 OOC 综合见 [M08](doc/m08.md)；
固定 DDR→DMA→M08→DMA→DDR 的 21 组板测已通过，见 [G2](doc/g2.md)。
实拍 JPEG 逐包加密及 640×480 连续 1000 帧 47.168 fps 的板测见 [G3](doc/g3.md)；
这是板端采集/加密吞吐，不是尚未接入的 USB 端到端帧率。
USB Slave 已完成独立 30 秒、16.37 MB/s、逐字节正确性验证；第一版传输方案已从
PS 以太网改为 PS USB0 CDC，复现及边界见 [USB 可行性测试](doc/usb_probe.md)。
M11 固定协议记录与两张实拍 JPEG 的 USB 往返也已验证；M12 离线认证回放见
[M12](doc/m12.md)。实拍 USB 视频 G4 明文 30 分钟 47.258 fps、G5 固定测试密钥
AES-GCM 60 秒 47.270 fps 与 Tag 篡改拒绝已通过，见 [G4/G5](doc/g4_g5.md)。
G6 开发态 ML-KEM 动态 USB 握手、双会话换钥、篡改拒绝与 DTR 重连实拍已通过，
见 [G6](doc/g6.md)；生产级密钥/熵源、G7 长测与完整 G0 仍待验收。
M02 SCCB/OV5640 初始化、失败保护和仿真已编写，复现及硬件状态见 [M02](doc/m02.md)。
M03 DVP/JPEG 字节采集与帧边界检查已编写，连续 1000 帧和故障恢复仿真通过，见 [M03](doc/m03.md)。
M04 原生异步 FIFO、整帧提交和 32/64-bit AXIS 已编写，默认帧长上限 64 KiB，见 [M04](doc/m04.md)。
M05 原生 AXI DMA、DDR 双缓冲、缓存/中断恢复和图片保存已通过实物验证：
缓存开关各 10000 次传输及 1000 帧真实 JPEG 采集；记录见 [M05](doc/m05.md)。
没有临时 BRAM/JTAG 快照旁路。
`tb_heartbeat.sv` 位于 `sim/tb/`，由 M01 回归执行，验证 PL LED 心跳的分频与复位。

## 优先：图片 AES MVP

PL 使用固定版本的 [secworks/aes](https://github.com/secworks/aes)（BSD-2-Clause），
PS 执行 GHASH，主机经 JTAG 传输并用独立 AES-GCM 认证解密。单张图片最多 512 KiB。
默认 `-O3` 构建，GHASH 使用无秘密索引表的 32-bit 字运算；性能对比见 MVP 文档。
无需新 Python 依赖；使用已有 cryptography、原生 Vivado/Vitis 和 Icarus/GCC。

```powershell
& ./.venv/Scripts/python.exe sim/tb/test_aes_mvp.py
& ./prj/build_aes_mvp.ps1 -BuildName aes_mvp_demo
# 接好 JTAG，保持板卡供电；下面会复位 PS 并临时替换 PL/裸机应用。
& ./.venv/Scripts/python.exe src/host/aes_image_mvp.py --workspace build/vitis/aes_mvp_demo
# 或加密自己的 PNG/JPEG 文件（<=524288 字节）：
& ./.venv/Scripts/python.exe src/host/aes_image_mvp.py 'D:/pictures/test.jpg' --workspace build/vitis/aes_mvp_demo
```

输出目录含密文、认证后还原图片、结果清单和本地测试密钥，默认在 Git 忽略的
`data/captures/` 下；不写 SD/Flash。本演示不是安全部署或视频吞吐验收。

## M00 复现

需要 Python 3.12+ 和可用 C99 编译器（默认 gcc，可用 CC 指定）。Windows PowerShell：

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
& ./sim/scripts/run_m00.ps1
```

测试离线运行，编译可移植 C 协议代码，并验证标准向量、尾块、篡改、控制消息拆包和 C/Python 互操作。
已有向量保存在 `data/kat/` 与 `sim/vectors/`；重新生成确定性向量：

```powershell
& ./.venv/Scripts/python.exe sim/scripts/generate_vectors.py
& ./.venv/Scripts/python.exe sim/scripts/generate_vectors.py --check
```

需要重新导入 NIST 标准向量时才联网运行：

```powershell
& ./.venv/Scripts/python.exe sim/scripts/fetch_kat.py
```

导入脚本固定来源提交和 SHA-256，保存筛选后的标准向量及来源清单。
AES-GCM 长度覆盖 0、1、15、16、17、31、32、1400，附独立 GHASH 逐块中间值。
所有向量密钥、私钥和种子都是公开测试数据；ML-KEM Python 库仅用于离线参考。

协议字段、消息类型和后续会话约定见 [doc/protocol.md](doc/protocol.md)。
C 代码无需 OS、堆或平台头文件，后续可直接加入 Vitis Standalone 工程。
Linux/macOS 使用 `.venv/bin/python sim/tb/test_m00.py`，向量脚本同理。

## Git 提交前校验

启用仓库内的 pre-commit hook：

```powershell
git config --local core.hooksPath .githooks
git hook run pre-commit
```

每次 `git commit` 会先检查暂存改动的空白错误，再验证向量可复现性并运行 M00/M01/图片 MVP/M02/M03/M04/M05 离线测试。
任一步失败都会阻止提交；hook 不生成向量、不暂存文件、不自动创建提交。
校验使用当前工作区内容，部分暂存时需确保工作区与拟提交内容一致；M01 需要 Icarus/vvp 和原生 GCC。
M04/M05 需要已安装 Vivado 的 XSim/XPM，工具不在 PATH/默认位置时设置 `VIVADO_ROOT`；不需要板卡。
Linux/macOS 首次启用还需 `chmod +x .githooks/pre-commit`。

## M01 输入与预检

参考 [board/README.md](board/README.md) 核对资料与实物版本。
在空的 `board/vendor/` 中按需导入用户提供的官方源码（保留原始文件，不覆盖已有文件）：

```powershell
& ./prj/import_vendor.ps1 -SourceRoot 'D:/BaiduNetdiskDownload/正点原子领航者/4_Source_Code'
```

然后运行工具/资料预检：

```powershell
& ./prj/check_environment.ps1 -ToolRoot 'D:/AmdDesignTools/2026.1'
```

M01 离线自检与完整构建：

```powershell
& ./sim/scripts/run_m01.ps1
& ./prj/build_m01.ps1 -ToolRoot 'D:/AmdDesignTools/2026.1'
```

Zynq-7000 器件支持已安装；按用户确认的两颗海力士 DDR，独立 BD、bitstream、
XSA 和对应 ELF（含 SD0 / 同平台 FSBL）已构建通过。CF7020B / COM4 已临时 JTAG 验证
UART、DDR scratch 和定时器；实物 YT8521 已识别并加入最小适配。PS GEM/echo 是历史
实验，第一版现改用 USB0；LED 实测、冷启动 30 分钟及 USB 视频整机验收仍待完成，M01/G0 尚未通过。

源码分别位于 `src/rtl/`、`src/ps/`、`src/host/`，仿真位于 `sim/`。
生成工程统一放 `build/vivado/` 和 `build/vitis/`，捕获/固件输出分别放
`data/captures/` 和 `board/output/`，均不提交 Git。官方原始资料放 `board/vendor/`，也不提交。
