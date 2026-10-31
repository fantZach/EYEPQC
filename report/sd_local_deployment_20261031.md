# SD 本地身份模式实际写卡记录

后续用户反馈：已将卡插回板上，按普通启动流程操作后回复“可以了”，确认实际连接可用。
没有执行独立读卡器重插复核，也未补充严格无JTAG冷启动和完整故障/长稳证据；下文待完成项仅按各自实际证据更新。

2026-10-31 用户明确要求“写卡”。北京时间 23:07:28 写入完成；本轮未格式化、改分区或写原始磁盘，没有访问板卡、启停视频服务、更改账号/TLS/手机配置。

## 核对与准备

- 实际目标：F: / Disk 1 / Partition 1；DD-TEK READER，序列号 `0123456789AB`，USB，MBR，31,266,439,168 字节，非系统/启动盘；EYEPQC/FAT32。
- 写前根目录只有旧 BOOT 和五份历史备份，没有私钥/随机状态文件或本次暂存文件。
- 来源：`build/vitis/g6_sd_local_identity_20261031_3/g6_usb/boot/BOOT.BIN`，4,337,104 字节，SHA256 `c9256bf45a2789640f26a77d6333d13a715c71ce133ce59e56c0dcb022ee1381`。
- 写前再次运行 `verify_software.py`，84 项哈希、实际 BSP 查表、应用/FSBL 启动校验通过；无板卡访问。
- 显式复用既有受保护身份，通过已测试的 `prepare_sd_identity.py` 在新的本机受保护目录准备三份私有材料及公开信息；独立生成新的初始随机状态。
- 公钥完整 800 字节与现有 schema2 配对相符，SHA256 指纹仍为 `a14a7f6fe9e862b90e66e413e4d0fcdbfc63e1b8bc0c0ff31e11324482927928`。未更换手机 pin。

## 实际写入

主代理审阅并执行本次一次性 PowerShell 脚本；脚本和敏感准备目录仅存于 Git 忽略的 `board/output/`，没有加入公开包或源码。
每次卡写前重新核对磁盘/分区/卷身份，拒绝链接路径和已存在的保留文件名；使用 CreateNew、WriteThrough、Flush(true)，重开逐字节读回比较。

1. 旧 BOOT 校验后排他备份到本机 `board/output/sd_local_write_20261031_1/BOOT.before-sd-identity.BIN`。
2. 卡根目录新建 `EYEKEY.BIN`（1632 字节）、`EYERNG0.BIN` 和 `EYERNG1.BIN`（各 80 字节），全部读回一致；两状态槽初始均为第 0 代。
3. 写入并核对 `BOOT.NEW`；旧 BOOT 改名为卡上 `BOOT.G6.PRE_SD_IDENTITY.20261031.BAK`，再提升新 BOOT，不覆盖已有文件名。
4. 新 BOOT hash、本机/卡上旧 BOOT hash 和其余五份历史备份保持检查均通过。

旧 BOOT SHA256：`08702a82f60594800b811ff2017d1dfb165c7cf88834a77d91f19552aa5b7e1b`。
脱敏本机结果：`board/output/sd_local_write_20261031_1/result.json`，状态 `SD_FILES_WRITTEN_READBACK_OK`；没有记录私钥、seed 或私有状态文件哈希。

## 待完成

- 整读卡器安全弹出、USB 拔插后的独立读回复核尚待用户操作，不能将本次缓存可见的读回视作该检查通过。
- 无 JTAG 实际 SD 冷启动、首次手机连接、手动换钥、重启及其他验收仍由用户完成；`board_validated=false`，不关闭任何 G 门禁。
- 持久性复核通过且新卡回板上电后，此模式使用普通 `eyepqc run`；旧固件不能仅删除开发参数就转换模式。
- 本机初始材料不得再次复制恢复到已用卡；故障恢复保留身份时必须生成新随机状态。首次配置端曾知悉秘密，SD 回滚及控制器任意断电持久性限制仍然存在。
