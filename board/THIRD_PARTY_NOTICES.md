# 板端候选包许可与分发限制

本包只用于操作者本机的开发/验收，`local_use_only=true`；不是授予外部分发权或生产安全认证。
项目自研部分采用根目录的 [MIT 许可证](../LICENSE)。AMD 工具链、生成 bitstream、BSP/FSBL 及其链接依赖的外部分发许可审查尚未闭环，
因此不要把本地候选 ZIP/BOOT.BIN 上传 GitHub Release 或转发给第三方；需由权利人先确认允许的分发范围。
如果不能接受相应条款，请使用仓库源码在自己的合法工具环境中构建，不使用这个二进制候选。

本地包保留下列上游原始文本，不能删除原版权/条件/免责声明：

| 内容 | 包内文本 | 来源 |
|---|---|---|
| secworks AES RTL | `licenses/secworks_aes.txt` | `board/src/rtl/crypto/secworks_aes/LICENSE` |
| mlkem-native | `licenses/mlkem_native.txt` | `board/src/third_party/mlkem/LICENSE`，按各源文件标识适用 |
| Intel TinyCrypt SHA-256 | `licenses/tinycrypt.txt` | `board/src/third_party/tinycrypt/LICENSE` |
| AMD embeddedsw / BSP / FSBL 上游许可集合 | `licenses/amd_embeddedsw.txt` | 实际构建环境 `Vitis/data/embeddedsw/license.txt` 原文 |

随附 AMD 许可集合用于保留上游通知，不说明其中所有条款都适用于本映像，也不替代 bitstream、工具生成物、
newlib/libgcc 等链接依赖的完整逐项分发审查。包内不得包含工具安装目录、完整厂商例程或未经核实的其他文件。

开发态测试身份和启动 seed 不嵌入本包，不得自行往 ZIP、SD 或发布附件加入这些文件。
BOOT 由哈希验证过的本地构建提供；此检查不等于签名启动、抗恶意本机篡改或生产供应链认证。
