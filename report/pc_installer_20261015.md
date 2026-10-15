# Windows 当前用户安装包（2026-10-15）

## 范围与安全边界

Ponytail：复用原生 Windows/Inno Setup、既有 Python CLI、严格账号/schema2/TLS 校验及 .NET ACL 实现，
未增加业务框架、账号网络服务、后台自启动或板端/手机协议改动。
数据放在 `%LOCALAPPDATA%/EYEPQC/pc/data/{private,public}`，程序位于同级 `bin`，设置仍为 `pc/settings.json`。
六个运行材料只在明确安装/`install-data [--config FILE]` 时从已有可信配置导入；
配置 show/set 不读取秘密文件。安装包本身不打入真实账户/密码/TLS 或 SSH 私钥/CA 签发私钥/板端密钥或 seed/login.txt。

导入预检格式及大小、账号 schema、schema2 身份、TLS 证书/私钥匹配、本地 ssh-keygen 解析；
不联网、不修改来源、不改变身份、没有密码输出。私有 ACL 只允许当前用户和 SYSTEM；
独占新建、flush/readback、实际副本重验后原子保存设置，失败逐一回滚本次明确创建的文件和目录，不递归删除。
升级已有完整数据只校验复用，不覆盖后续维护的账户/身份；部分数据、坏设置、重解析点或 ACL 异常均拒绝。
导入阶段失败保留旧状态；但其成功后若 Inno 的程序复制阶段再失败/取消，已迁移的有效材料和设置可能保留，
不声称安装器整体事务回滚。卸载保留材料和设置。

当前真实旧服务不停止、不覆盖、不重复启动；安装器不运行服务、不改系统 PATH、不接 USB/JTAG。
1.2.1 增加当前用户 HKCU PATH 注册，详见下节；不使用管理员权限或系统 PATH。
安装包切换后的实板/公网/手机帧率与长期验收不由本轮离线 fixture 替代。

## 1.2.1 当前用户 PATH

安装程序目录 `%LOCALAPPDATA%/EYEPQC/pc/bin`，只对 HKCU `Environment\Path` 追加缺少的项。
读取未展开的原始字符串；Inno `RegWriteStringValue` 保留既有 REG_EXPAND_SZ 类型，否则使用 REG_SZ：
[官方 API 说明](https://jrsoftware.org/ishelp/topic_isxfunc_regwritestringvalue.htm)。
原内容、环境变量、空项与尾分号不被重新格式化；既有非字符串 PATH 拒绝安装，不覆盖。
只在去重比较时展开环境变量、忽略大小写、外层引号/空白及尾部斜杠。
独立 HKCU `Software\EYEPQC\pc\InstallerPath` 记录新增项的所有权及原始快照，升级保留该归属；
既有等价项不创建归属，卸载不会删掉操作者预先设置的项。

卸载时原值未变则恢复原始值/原来不存在的状态；有外部修改时仅删除唯一、精确一致的自有目录项，
不覆盖整份旧快照。目标改写或出现多个精确项时保守保留。其他项与当前字符串类型保留。
安装写入前复读检测已观察到的并发修改；Registry 字符串更新并非跨进程 compare-and-swap，
安装/卸载时不应同时用其他工具编辑 PATH。
`ChangesEnvironment=yes` 使用原生通知；[官方说明](https://jrsoftware.org/ishelp/topic_setup_changesenvironment.htm)。
旧 PowerShell/Windows Terminal 进程不会自动替换自身环境，需关闭旧窗口/退出 Terminal 再重新启动。

主聊天独立完成当前机器的一次性配置修复（并非执行新安装器）：
核对安装 EXE 后向 HKCU 追加目录，结果 Changed=true、REG_SZ 类型保留、原项保留、环境广播成功；
刷新测试进程后 Get-Command 定位到用户 bin，实际安装仍为 1.2.0。
该手工 PATH 没有安装所有权标记，后续 1.2.1 安装/卸载应保留。

同时主聊天发现旧 1.2 手工安装的六个 data 文件存在，但设置仍引用仓库 tmp。
六组源/副本 SHA256 逐一比较均相同，旧配置 check 通过后，先排他备份
`settings.before-user-data-fix-20261015.json`，再以六次显式 `config set` 将设置转到用户 data。
随后 `install-data` 校验既有数据/ACL 返回 DATA_INSTALL_OK，`check` 返回 CONFIG_OK。
没有修改账号/私钥正文或重启服务。保留了现有升级路径不一致即拒绝的 guard；
这项独立修复不证明旧安装事务完整成功，也不是新版真实升级验收。

## 工具与火绒告警事实

官方来源与说明：

- [官方下载](https://jrsoftware.org/isdl.php)：Inno Setup 6.7.3，发布者 Pyrsys B.V.。
- [官方签名校验说明](https://jrsoftware.org/isdl-verify.php)。
- [当前用户非管理安装](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)。
- [CloseApplications](https://jrsoftware.org/ishelp/topic_setup_closeapplications.htm)：明确设 no，RestartApplications 也设 no。

实际下载 URL：`https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe`。
下载包本地 SHA256：`9C73C3BAE7ED48D44112A0F48E66742C00090BDB5BEF71D9D3C056C66E97B732`。
执行前 Windows Authenticode 显示 Valid，Subject 为 `CN=Pyrsys B.V., O=Pyrsys B.V., S=Noord-Holland, C=NL`。
该 hash 当时是本地计算值，未独立与官方发布 hash 比对；不把固定记录本身当作额外的来源认证。
工具以 CURRENTUSER/NOICONS 安装到项目 `build/pc_installer/tools/inno-6.7.3`，未加 PATH；
工具安装程序已退出 0，未记录其 PID。该动作并非安装 EYEPQC。

原构建脚本具有 Invoke-WebRequest 下载 EXE，再 Start-Process 静默/隐藏安装工具的行为。
火绒将 `pc/build_installer.ps1` 标记为 `HEUR:TrojanDownloader/PS.NetLoader.ae`，病毒 ID `D3D77FB36307344A` 并删除；
主代理当时只读该脚本的 pwsh PID 29048 亦与告警关联。
子代理最后尝试修补时发现文件已不存在，因此未执行到随后计划的构建命令；
原 `build_installer.ps1` 从未被执行，其下载功能也未经该脚本执行（上述单独的官方工具下载/安装确实执行过）。
发现后停止所有工具/编译工作，未从隔离取回、改名混淆、加白、关防护或调整策略。
精确启发式规则未知，不能确认为误报或感染。

用户要求解释并继续后，在同一正常源码路径编写新的**纯离线**构建脚本：
只接受已存在的 ISCC，验证其 Authenticode/发布者/固定二进制 hash，再编译；
无任何下载、工具自动安装或依赖安装功能。使用原有隔离 venv 打包，不传 InstallDependencies。
这是真实移除风险行为，不是改名/隐藏行为来绕过检测；再次拦截时应立即停止。

首次离线构建在任何编译前由自身 PE 版本检查拒绝：ISCC 的 FileVersion/ProductVersion 实际均为 `0.0.0.0`，
该失败不是杀毒拦截。现改为签名与精确编译器 hash 双重检查：
`0A8757031B33777E4C9CBFFEE40F11A5062B36D25CBE144C1DB73B6102B80AD7`；
同一文件的 Authenticode 仍为 Valid/Pyrsys B.V.。不通过放宽防护策略处理此版本字段问题。

## 验证记录

- 告警前 `test_install_data.py` 12 项通过（10.182 秒），均为隔离 LOCALAPPDATA 与合成材料。
- 后续增加坏 tunnel 类型、离线脚本/非管理安装契约检查，以及独立 AppId 的可选真实安装生命周期测试。
- 生命周期 fixture 编译 AppId 为 `{BC45B197-2603-498A-B857-C58A97E11DC0}`，
  与生产 `{9B9AF3F4-737E-48FD-B6A3-6B0A82BA6A7D}` 分离；显式 `/DIR`、`/NOICONS`，
  给父安装进程传隔离 LOCALAPPDATA 并由子 EXE 继承，不假设 Windows KnownFolder 会重定向。
- 当前定向账号 11/11（8.031 秒）、材料导入 13/13（9.729 秒）通过。
- 真实 fixture 首轮 2 测试中一个通过，矩阵因错误地在升级时继续传 SOURCECONFIG，
  正确触发材料导入的显式旧源覆盖拒绝；42.117 秒报告 9 个子场景失败及后续隔离清理错误。
  修正测试为升级使用已保存设置，不放宽生产 guard。已核对该轮 build 根内八个 fixture 卸载程序，
  各自正常退出 0，清理独立 AppId/空注册表分支，保留失败日志和合成 data，未删用户资料。
- 新 fixture 根 `build/pc_installer/path_fixture_20261015_2` 重测 **2/2 通过，51.927 秒**：
  六项材料导入/读取、维护后升级不覆盖、卸载保留资料/设置、缺失与空 PATH、普通 REG_SZ、
  REG_EXPAND_SZ 原始环境变量/空项/尾分号、预存大小写/引号/尾斜杠/ENVVAR 等价项、
  重复升级、外部追加、目标被改写/重复、非字符串拒绝。真实 HKCU Environment PATH 原始值及类型不变；
  独立 fixture AppId/注册表项已正常卸载清理。该矩阵执行实际 Pascal，不是影子算法测试。
- 唯一一次默认全 PC 回归：99 项、61.042 秒，96 通过、2 项显式安装跳过、1 项旧 settings 测试的
  fixture 构造错误（在故意无效的 LOCALAPPDATA 下调用 defaults，尚未进入被测配置加载）。
  修正 fixture 构造时机，并把冻结设置测试改为优先 1.2.1，定向 **11/11 通过、7.341 秒**。
  未再跑整套，不将首轮失败标记为全套一次通过。
- 冻结新 EXE `--version`、`--help`、`account --help` 均退出 0；归档清单 86 项，
  六种真实运行材料文件名及 login.txt/CA 签发私钥/board seed 命名检查零命中；
  accounts/install_data/private_acl/cli_settings 模块包含。源码构建未指定任何资料 add-data。
- 当前未声称成品杀毒扫描通过、安装包代码签名或新版业务链路实测通过。

## 冻结产物（离线构建，旧 1.2 文件保留）

| 文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| `build/pc_cli/dist/eyepqc-1.2.1.exe` | 10284731 | `3896D9344388F12F1E490E1090BB895DF926229E1EAB68A728A9B2316D9510C7` |
| `build/pc_installer/dist/EYEPQC-Setup-1.2.1.exe` | 12125483 | `1167212C75CF6522767C705F3FBFA72ED754F2A0C5C052EB9B4A3944CEBA6F39` |

正式 AppId 保持 `{9B9AF3F4-737E-48FD-B6A3-6B0A82BA6A7D}`，支持在用户停止旧服务后手工升级；
本代理只运行了独立 AppId 和测试目录的 fixture，不升级真实安装、不改真实账户或服务、不接硬件。
