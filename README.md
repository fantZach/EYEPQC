# EYEPQC

领航者 Zynq-7020 单向 JPEG 加密视频项目。实施顺序见 [doc/steps.md](doc/steps.md)，
目标见 [doc/goals.md](doc/goals.md)，最新进度见 [report/progress.md](report/progress.md)。

目前完成 M00 协议与离线黄金参考；已解压并研究官方 7020 例程，
板级参数、JPEG 数据路径及迁移问题见 [研究记录](report/vendor_examples.md)。M01/G0 尚未上板通过。

## M00 复现

需要 Python 3.12+ 和可用 C99 编译器（默认 gcc，可用 CC 指定）。Windows PowerShell：

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
& ./sim/scripts/run_m00.ps1
```

测试离线运行，编译可移植 C 协议代码，并验证标准向量、尾块、篡改、TCP 拆包和 C/Python 互操作。
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

每次 `git commit` 会先检查暂存改动的空白错误，再验证向量可复现性并运行 M00 测试。
任一步失败都会阻止提交；hook 不生成向量、不暂存文件、不自动创建提交。
M00 校验使用当前工作区内容，部分暂存时需确保工作区与拟提交内容一致。
Linux/macOS 首次启用还需 `chmod +x .githooks/pre-commit`。

## M01 输入与预检

参考 [board/README.md](board/README.md) 核对资料与实物版本。
在空的 `board/vendor/` 中按需导入用户提供的官方源码（保留原始文件，不覆盖已有文件）：

```powershell
& ./prj/import_vendor.ps1 -SourceRoot 'D:/BaiduNetdiskDownload/4_Source_Code'
```

然后运行工具/资料预检：

```powershell
& ./prj/check_environment.ps1 -ToolRoot 'D:/AmdDesignTools/2026.1'
```

源码分别位于 `src/rtl/`、`src/ps/`、`src/host/`，仿真位于 `sim/`。
生成工程统一放 `build/vivado/` 和 `build/vitis/`，捕获/固件输出分别放
`data/captures/` 和 `board/output/`，均不提交 Git。官方原始资料放 `board/vendor/`，也不提交。
