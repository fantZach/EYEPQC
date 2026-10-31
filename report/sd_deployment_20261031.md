# G6 SD BOOT 更新记录 — 2026-10-31

用户明确要求将新 BOOT 写入已接电脑的 SD 卡，并回复继续。仅更新启动文件，未格式化、改分区、写原始磁盘或操作板卡。

## 目标与来源

- F: / Disk 1 / Partition 1，DD-TEK READER，序列号 `0123456789AB`，USB，31,266,439,168 字节，MBR，非系统/启动盘。
- 卷标 EYEPQC、FAT32，卷大小31,257,001,984字节。写入前再次核对设备、容量、分区类型、卷标及旧BOOT哈希。
- 来源：`build/vitis/g6_sd_usb_bootstrap_20261016_6/g6_usb/boot/BOOT.BIN`，4,303,824 字节。
- 重新运行 `board/prj/verify_software.py`：BSP查表、应用/FSBL ARM启动及79项哈希通过；没有板端验收结论。
- 新SHA256：`08702a82f60594800b811ff2017d1dfb165c7cf88834a77d91f19552aa5b7e1b`。

## 实际写入

旧BOOT为 `_5`，4,303,696字节，SHA256 `1ffcef7daea201da6735ab6992e5c0fd40af95ec9f707e96763bcba5567bcfca`。
先排他创建本机备份 `board/output/g6_sd_deploy_20261031_6/BOOT.G6.before-clearhalt.BIN`，WriteThrough/Flush(true)并读回核对。
再以CreateNew/WriteThrough/Flush(true)写 `F:/BOOT.NEW`，核对新hash后，原BOOT保留为
`F:/BOOT.G6.PRE_CLEARHALT.20261031.BAK`，新文件提升为 `F:/BOOT.BIN`。

最终新BOOT及卡上/本机旧备份分别与预期hash一致。原四份G0/G6历史备份逐一复读，全部保持原hash。
无删除、不覆盖已有备份、不更换身份或seed、不变更PC程序/服务/账号/证书。

## 仍待用户

- 当前仅写入后读回通过，**整读卡器拔插后的持久性尚未复核**。
- 请Windows安全弹出F:，整个读卡器USB拔下再接回，SD留在读卡器内；重新识别后再核对BOOT及备份。
- 新固件首连、SD冷启动、手机视频及其他验收仍由用户统一执行，均不在本轮标为通过。
- `_6` 是开发态候选；PC仍须显式USB初始化，BOOT不包含实际开发私钥或seed。不宣称生产安全或首次查询问题已实板解决。
