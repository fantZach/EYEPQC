# 四端候选交付与软件检查记录

日期：2026-10-31；候选集合：`v1.1.0-rc1`。源码开发从已发布 v1.0.0 的提交 `a37437d` 开始。
按用户决定，部署执行和最终验收由用户统一进行；本轮不连接板卡、手机或现网服务器，不升级实际安装的 PC 程序。
现有 v1.0.0 标签/附件保留，不创建新的正式稳定版 Release。

## 实际完成

### Board

- 新增 `package_candidate.py`：每次重新执行既有软件校验，只白名单导出 BOOT、脱敏清单、教程和必要许可。
  拒绝覆盖、链接路径、错误 profile、过期来源/hash 和嵌入身份/seed 的构建声明。
- 新增显式 `prepare_dev_identity.py`：全新部署时在私有 ACL 验证后取 OS 随机数生成开发身份，
  通过真实 PC bootstrap 的私钥/内嵌公钥/SHA3-256 `H(ek)` 校验；不保存独立生成输入、不输出秘密。
  只在临时测试目录执行，未为用户创建/替换真实身份；已有身份必须复用。
- 复用 `_6` BOOT，4,303,824 字节，SHA256 `08702a82f60594800b811ff2017d1dfb165c7cf88834a77d91f19552aa5b7e1b`。
  当前源码/BSP/ARM/FSBL、79 项哈希与 709 项生成输入复核通过，仍 `board_validated=false`。
- [Board 教程](../board/DEPLOYMENT.md) 覆盖构建、首次身份、SD 身份核对/备份/写入/读回/拔插、
  无 JTAG 冷启动、USB 及回滚；不以本文或候选包认定首连故障已修复。

### PC 1.4.0-rc1

- 安装器默认仅安装程序，缺少运行材料不再阻止新电脑安装；显式导入仍严格核对旧材料。
- `eyepqc init` 仅创建空私有/公开目录和配置，隧道默认关闭；已有或并发出现的配置不覆盖。
  首账号通过 `account add` 隐藏双确认创建；缺证书/配对时 `check/run` 明确拒绝，不启动 USB/服务。
- 新增开发机独立部署 TLS 工具：显式新目录生成部署 CA/IP SAN 叶证，或显式复用受保护的原 CA 续签。
  检查私有 ACL、CA 用途/签名/公私匹配/期限，叶证期不超过 CA；不生成账号、板端身份或改服务。
- 共享 `_new_file` 增加 flush/fsync 和本次新文件失败清理，原配对/调试 TLS 调用方回归通过。
- [PC 教程](../pc/DEPLOYMENT.md) 包含从零安装、身份/配对/证书/SSH 材料来源、实际 IP、账号维护、
  启停/备份/升级/回滚/排错；证书准备工具要求完整源码与 `.venv`，不把不完整裸脚本当独立 EXE 功能。

### Android 0.9.0-rc1

- 新增 release 外部 keystore 环境变量签名和 `-RequireSigned`；缺材料不回退 Debug key。
- release 非 debuggable、禁止明文流量、不预填开发 IP；默认系统 CA，显式部署 CA 只进入 release 生成资源。
  拒绝私钥、多证书、过期/叶证书、旧 Debug CA，保留链/地址/有效期检查；显式 CA → 默认构建无残留。
- 增加 TLS/DNS/超时脱敏提示，空地址展开设置，密码关闭视图状态保存。
- [Android 教程](../mobile/DEPLOYMENT.md) 覆盖 IP WSS、公开 CA、签名/备份、Debug→Release 签名冲突、
  登录/自动配对/指纹、升级/回滚及用户自验。
- 交付 debug APK 供调试；同时提供 **不能安装的 system-only release-unsigned APK** 以核对构建隔离。
  正式长期签名材料未指定，部署公开 CA 也未在用户环境建立，不能宣称正式可安装 APK 已交付。

### Server 1.0.0-rc1

- 新增固定源码白名单打包工具，不递归纳入运行 config、authorized_keys 或 host 私钥。
- [Server 教程](../server/DEPLOYMENT.md) 覆盖首次安装、实际 Linux 校验、服务启停、权限、公钥/host key 独立核验、
  安全组边界、升级/换授权/回滚/排错；原管理 SSH22 不变。
- 原 `prepare_tunnel.py` / 受限 sshd / systemd 模板业务限制不改，本轮没有现网部署或真实 Linux 验收。

## 软件检查结果

所有 Python 命令使用项目 `.venv/Scripts/python.exe`；移动构建使用已有本机 JDK/Gradle/SDK 离线缓存。

| 范围 | 结果 |
|---|---|
| Board 新身份与打包 | 各 8 项临时 fixture 测试通过；根协调独立复跑 8+8 项通过 |
| PC 全套 | `python -m unittest discover -s pc/tests -v`：133 项，130 通过，3 项安装生命周期显式跳过；80.910 秒 |
| PC 真实隔离安装 | 用独立 Fixture AppId/目录/registry 另跑上述 3 项，全部通过，39.239 秒，含 9 种 PATH 场景；未操作实际用户安装 |
| 原配对/TLS及新部署 TLS | 15 项通过；根协调另复跑 init 9 项、部署 TLS 6 项通过 |
| PC 冻结程序 | `--version` 为 1.4.0-rc1；9 个自有模块 code object 与当前工作区源码一致；86 CArchive/271 PYZ，无真实材料成员 |
| Android Java | 核心160/配对57/临时KEM37/UI49/诊断7，共310项断言通过 |
| Android HTTPS/TLS | 自动配对10场景、本机TLS/SAN/HTTP/接管4场景通过 |
| Android Gradle 集成 | 3 组通过，102.4秒，无skip；CA拒绝、显式→系统CA隔离、临时外部签名/SDK验签、缺签名拒绝、输出不覆盖 |
| Android 最终构建 | debug/release 31/43 tasks、vital lint、Debug v2 签名和 CA 隔离通过；保留已有 JDK/缺 platform-tools 提示 |
| Server | 原16+打包7，共23项通过；根协调独立复跑通过，未调用真实Linux sshd/systemd |
| 根协调跨端互操作 | `sim/tb/test_account_three_end.py` 1项/13.549秒，`test_cloud_passthrough.py` 1项/13.851秒，通过 |
| 四包结构 | CRC/唯一成员/路径安全/白名单秘密文件名/内置清单核对通过，共38成员 |
| 提交门禁 | 继续使用原 M00/M10/M12/G5 hook；不扩充默认检查，不绕过提交门禁 |

跨端测试使用模拟 USB/相机与公开测试凭据、本机隔离 TLS，不是 Android 真机或公网/实板验收。
测试覆盖正常、手动/计时换钥、STOP、重连；计时换钥是 fixture 驱动，不能称实际跨 30 分钟。
部分 fixture 主动关闭连接产生预期 1006/1011 日志，不将“测试通过”写成所有日志零错误。

## 固定本机附件

目录 `build/releases/v1.1.0-rc1/`（Git 忽略，不上传 Board 二进制）。

| 文件 | 字节 | SHA256 |
|---|---:|---|
| `EYEPQC-Board-development-candidate.zip` | 663,545 | `681f0afc0c0147b1bd70e5a6c44fd65a87c4947300460f037e76b4ba5917080d` |
| `EYEPQC-PC-1.4.0-rc1-windows-x64.zip` | 21,690,935 | `0eb36d18e22567685a44d7c683f8cff960e29dc703a1f1c206d3d42775ba0c1d` |
| `EYEPQC-Android-0.9.0-rc1.zip` | 8,900,968 | `733d9b99a7db05cf82edc2d30f3224279bc87f77648711910264181e95b91b59` |
| `EYEPQC-Server-1.0.0-rc1.zip` | 17,847 | `84a751031bd35d4eef5f9736186dbe17532538c1bb5e7d32a7b7ad36251a41b1` |

PC CLI SHA256 `2918ecc09a500c192dfb5369431d01879845535326703d6a84fa9b428126815b`；
安装器 `f47e74bf46f286a88c5e58f8456c43377b3f4aa793debbd755785e3792961f8c`。
Android debug `de1c6311efd4d0f4f99c1efbcb078c5df2bdef573f0cb3dbd07d7ac55fdf394e`；
release-unsigned `1b80dd29e908b4e909234d8d69f12fb6ca08c3db3ffa20d94c483fccadda54e3`。

Board 首个未含新身份教程的包未删除，已按精确源 hash 和路径检查保留至
`build/releases/previous-board-20261031/EYEPQC-Board-development-candidate-before-identity-guide.zip`；
旧 hash `62d8dd70720b29defa3981997a466be682583bc922578e5b0263eb0d967b7ddc`，不要混作最终候选。

## 限制与下一步

所有用户/物理/公网验收均 pending；Board 仅本机自验使用，AMD 生成物外部分发权利尚需核实。
PC EXE 未商业签名；Android 长期 release keystore 和部署公开 CA 尚需操作者指定并安全保管。
旧 Debug CA 于 2026-11-12 16:59:03 UTC 到期；实际叶证可能更早过期，应核对当前证书而非沿用旧日志。
首次 USB 查询问题仍待用户实板结果。Python/Java/驱动进程内秘密副本完整物理清零不作保证。

按 [统一部署入口](../doc/deployment/README.md) 和 [验收表](../doc/deployment/ACCEPTANCE.md) 交接。
用户确认候选后再完成正式签名/版本冻结/发布；任何重建都会记录新 hash，不自动搬移旧候选验收结论。
本记录不声称四端正式稳定版已完成，也不声称生产熵源/密钥存储/可信启动已通过。
