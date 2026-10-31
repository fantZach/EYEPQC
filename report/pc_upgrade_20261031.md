# PC 本机升级记录 — 2026-10-31

用户明确要求安装新的 PC 程序。升级前确认旧版为1.3.2，未发现eyepqc进程或8765监听，不杀进程、不启动服务。

- 安装包：`build/pc_installer/dist/EYEPQC-Setup-1.4.0-rc1.exe`。
- 安装包SHA256：`f47e74bf46f286a88c5e58f8456c43377b3f4aa793debbd755785e3792961f8c`，与候选记录一致。
- 旧EXE已排他保留至 `build/pc_installer/upgrade_20261031_1/eyepqc-1.3.2.before-upgrade.exe`，
  SHA256 `a0b909ff674cc4902672476b98678196f31cffe3284ecfa32a906132b3bce160`，核对通过。
- 安装使用默认program-only模式，无SOURCECONFIG/IMPORTCURRENT参数，不导入、初始化或重置运行材料。
  安装禁止关闭/重启现有应用及系统，进程窗口隐藏；安装退出码0，日志保留在同一升级备份目录。
- 实际用户目录 `LOCALAPPDATA/EYEPQC/pc/bin/eyepqc.exe` 返回 `EYEPQC PC 1.4.0-rc1`。
- 新EXE SHA256：`2918ecc09a500c192dfb5369431d01879845535326703d6a84fa9b428126815b`，与候选CLI一致。

升级前后仅以hash/存在性核对8项文件：settings、accounts、TLS私钥、SSH私钥、板端测试身份、公开配对、
服务端证书链、known_hosts，全部状态一致，未输出内容。当前用户PATH完全未变，Get-Command解析到实际安装目录。

实际安装后的 `eyepqc check` 退出0：`CONFIG_OK offline_only=true board_validated=false network_started=false`。
检查后仍无eyepqc进程/8765监听；没有接触USB、板卡、手机或云服务。
本次只证明安装/文件保持及本地配置检查，不证明证书期限/SAN/手机信任、视频、SD冷启动或正式验收通过。

版本仍是1.4.0-rc1候选，EXE无商业代码签名；旧版和运行材料保留，未静默开始视频。
