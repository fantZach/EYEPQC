# 开发板子项目

领航者 CF7020B / XC7Z020，OV5640 接 P2，裸机运行，USB Slave 向 Windows PC 发送密文。
PL 负责 JPEG 数据通路和 AES-GCM，PS 负责会话、ML-KEM 和 USB。

## 当前使用

从 [新手部署](DEPLOYMENT.md) 开始，构建与历史兼容方式见 [进阶教程](DEPLOYMENT_ADVANCED.md)。
SD 保存 `BOOT.BIN`、固定身份文件及两个可更新随机状态文件，日常 PC 运行 `eyepqc run`。
运行卡升级只更新匹配的程序，不覆盖随机状态，不复制或恢复旧状态继续使用。
公开包不含私有材料，首次材料由可信配置者另行准备。

用户已确认当前版本连接可用，并反馈此前首次连接问题修复。本次文档整理未新增板测；其他故障与长稳项目继续按实际证据验收。
当前来源及离线检查见 [SD 实现记录](../report/sd_local_identity_20261031.md) 和 [版本记录](../doc/releases/first-stable.md)。

## 目录

| 目录 | 内容 |
|---|---|
| `src/rtl/` | 摄像头、FIFO、AXIS、AES-GCM、Keccak 实验 |
| `src/ps/` | 裸机固件、协议、会话与驱动适配 |
| `src/third_party/` | 固定版本密码库及许可 |
| `prj/` | 构建、检查与板测工具 |
| `xdc/` | 板级约束 |
| `vendor/`、`output/` | 本机资料和生成文件，Git 忽略 |

硬件使用 Vivado/Vitis 2026.1 与 Zynq-7000 器件包。资料核对见 [官方例程研究](../report/vendor_examples.md)，模块说明见 [实施顺序](../doc/steps.md)。
`package_candidate.py` 重新校验构建来源并按固定清单打包，不遍历或包含私有材料，也不写卡。
AMD/生成物外部分发审查尚未闭环，板端二进制包只供本机使用；见 [许可通知](THIRD_PARTY_NOTICES.md)。
本版不提供硬件熵、受保护存储或旧状态回滚保护，首次配置端须可信；见 [SD 身份边界](../doc/g6_sd_identity.md)。
