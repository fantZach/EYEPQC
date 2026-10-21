# 第三方组件与许可

本项目自研部分尚未指定统一开源许可证。保留代码可见性不等于授予开源再分发许可；
不得从下列组件的许可推断整个 EYEPQC 已采用 MIT、Apache 或 BSD。各组件遵循其自身许可。

## 仓库内组件

| 组件 | 许可与原始说明 |
|---|---|
| secworks AES RTL | [原始 LICENSE](board/src/rtl/crypto/secworks_aes/LICENSE)、[来源](board/src/rtl/crypto/secworks_aes/README.md) |
| mlkem-native | [原始 LICENSE](board/src/third_party/mlkem/LICENSE)、[来源及固定版本](doc/m09.md) |
| Intel TinyCrypt SHA-256 | [原始 LICENSE](board/src/third_party/tinycrypt/LICENSE) |

## 可执行程序

PC 可执行程序及 Android APK 的依赖/原始许可分别见 [PC 通知](pc/THIRD_PARTY_NOTICES.md)
和 [Android 通知](mobile/THIRD_PARTY_NOTICES.md)。Release 随附许可归档，须与二进制一同保留。
GitHub 自动生成的源码归档同时保留仓库中的原始许可证和版权头。

AMD Vivado/Vitis、BSP/FSBL、器件支持及板卡官方资料属于各自权利人，使用时需遵循相应工具链/厂商条款。
本次不打包工具链、厂商原始例程、未核实分发许可的 BOOT.BIN/XSA/bitstream 或其他本机生成工程。
FFmpeg、GCC、JDK、Android SDK 等构建/开发工具不因被文档引用而成为本次二进制附件。

本清单是实际使用范围的发布通知，不代替完整版权、专利或法律审查。
