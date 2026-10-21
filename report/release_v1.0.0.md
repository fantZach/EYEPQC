# v1.0.0 发布准备核验

日期：2026-10-21。代码基线 `158a97f120044e355c926f834862d3174eec79ed`；
项目发布使用新标签 `v1.0.0`，保留 PC 1.3.2 和 Android 0.8 组件版本。
本轮根协调负责 GitHub 发布，各端代理负责所属目录、产物及离线验证，未操作硬件、手机、运行服务或云端部署。

## 仓库整理

- 根 README 改为四端/下载/运行前提/安全边界/证据入口，移除过时的“公网未实现”和旧版状态摘要。
- 四端 README 增加当前发布状态，保留历史资料但标清历史 token/P2P/JTAG 方案不等于当前账号/SD 推荐路径。
- 新增 CHANGELOG、SECURITY、CONTRIBUTING、THIRD_PARTY_NOTICES、发布说明及各端完整二进制许可。
- 保持原目录和原历史报告，不删除本机忽略构建/资料，不选择项目统一开源许可证。
- 远端 `fantZach/EYEPQC` 预检为 private/main，有发布权限、无既有 Release/标签；不修改可见性。

## 离线核验

| 范围 | 命令/方法 | 结果及边界 |
|---|---|---|
| 板端 | `python board/prj/verify_software.py build/vitis/g6_sd_usb_bootstrap_20261016_6` | 79 项哈希、709 项生成输入、BSP 查表、ARM 应用/FSBL 启动通过；`board_validated=false` |
| PC CLI | `python -m unittest discover -s pc/tests -p test_cli.py -v` | 12 项通过 |
| PC 初始化 | 同上，`-p test_dev_usb_bootstrap.py` | 17 项通过 |
| PC 账号 | 同上，`-p test_account_commands.py` | 11 项通过，隔离 fixture，不改真实账号 |
| PC 设置 | 同上，`-p test_cli_settings.py` | 11 项通过；PC 四组共 51 项，无 skip |
| PC 产物 | CLI `--version`、PyInstaller CArchive/PYZ 清单与源码编译比对 | 版本 1.3.2；86/271 项，9 个自有模块 code object 与当前源码一致 |
| PC 安装器 | 静态 `[Files]` 清单与输入审查 | 仅 CLI 两用途，不含运行材料；未独立解压/重装，非新安装验收 |
| Android | `mobile/test.ps1`；本机自动配对/TLS 测试 | 303 项断言、10 项 HTTPS、4 项 TLS 通过，不是真机或公网验收 |
| Android 构建 | 现有 Gradle 8.9 离线 debug/release/vital lint、APK v2 签名与 CA 隔离检查 | 73 tasks 成功；保留既有警告；只分发 debug APK，release 未签名产物不分发 |
| Server | `python -m unittest discover -s server/tests -v` | 16 项通过；不连接服务器 |
| 发布工具 | `python tools/test_github_release.py` | 8 项通过；凭据只捕获到内存、禁止认证重定向、草稿/发布分离、校验完整资产及远端 SHA256 |
| 根协调独立复核 | ZIP CRC/成员/内部二进制 SHA256/清单，发布工具测试及只读 API inspect | 两 ZIP 内部二进制匹配固定哈希，17 个成员无真实材料；工具 8 项再次通过 |
| 提交门禁 | 原 `.githooks/pre-commit` | 提交时执行暂存空白检查及 M00/M10/M12/G5，不扩展默认 hook |

所有 Python 命令使用本机 `.venv/Scripts/python.exe`。Android 细节见
[交付说明](../mobile/RELEASE.md)，板端细节见 [README](../board/README.md)。
这些检查不新增冷启动、视频长稳、故障恢复、全屏/旋转 UI 或 G8/G9 通过结论。

## 敏感信息与许可检查

当前 Git 跟踪树进行私钥 PEM、GitHub token、AWS access key 和带值凭据赋值扫描；
156 个历史提交可达对象也检查了高置信私钥/token 模式。高置信命中只有
`server/tests/test_prepare_tunnel.py` 中 `abc` 伪造私钥头的拒绝测试；其他赋值命中核实为测试 fixture 或凭据字段解析。
未发现真实秘密命中；这是有限模式扫描，不保证完整安全审计。
运行材料和原始视频保持忽略，不读取/发布真实密码或私钥内容。

PC ZIP 保留 Python/Expat/OpenSSL/zlib/pySerial/websockets/PyInstaller/Inno 许可；
Android ZIP 保留 Apache/Bouncy Castle/MPL 公告及源链接；板端三项原始许可证随源码保留。
AMD 生成物分发许可未闭环，因此本次不附 BOOT/XSA/ELF/bitstream。不是完整法律或专利审查。

## 固定附件

| 文件 | 字节 | SHA256 |
|---|---:|---|
| `EYEPQC-PC-1.3.2-windows-x64.zip` | 21,695,102 | `16dfa9f1de1db366eb648e67d24f50f9cbcfcaa8f87524ab064d68266e0ef915` |
| `EYEPQC-Android-0.8-debug.zip` | 4,758,983 | `43328cdc6c3ccc5905f2348e608dc129d87d1749497ae102be3f292473e35ede` |
| `release-manifest.json` | 2,297 | `f90ae60d045b9317b5d62122897c4470ef9c8b3608a52a7065f6df50391578b4` |

PC ZIP 内 CLI SHA256 `a0b909ff674cc4902672476b98678196f31cffe3284ecfa32a906132b3bce160`，
安装器 `6a340b1f3c7aca3788bc34fa62860916671d0bc54225b6c8a5994ffc5e45da17`；
APK SHA256 `98dec91de15bb7e6158d4769efd62e0fe180ce6a3de89d07f8ba872e7d600db8`。
所有附件置于忽略目录 `build/releases/v1.0.0/`，不把二进制加入 Git 历史。

## 发布规则与保留问题

根协调将审核后的提交/注释标签推至远端，`tools/github_release.py --mode draft`
要求远端标签解析到指定 commit、上传完整目录并核对 GitHub state/size/digest；
随后独立 `--mode publish --release-id ...` 再次核验后发布，不自动覆盖/删除/重试已有资产。
任何 API 失败都应先检查远端状态；日志不输出认证信息。
发布入口固定为 [v1.0.0](https://github.com/fantZach/EYEPQC/releases/tag/v1.0.0)。

已知：首次 USB QUERY 可能超时，板端 `_6` 未上板；PC 安装需要已有可信材料，EXE 未商业签名；
Android 是 debug APK，测试 CA 到期时间为 2026-11-12 16:59:03 UTC；开发 PC 知道板端身份/seed。
无生产安全、实际两小时长稳、完整冷启动或故障门禁通过声明，详见 [发布说明](../doc/releases/v1.0.0.md)。
