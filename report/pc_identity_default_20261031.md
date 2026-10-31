# PC 1.4.0-rc2：省略开发身份路径参数

用户反馈手机已可连接，随后要求省去常用启动命令中的 `--dev-identity-file` 路径。
本次只实现便利默认值，不取消显式开发态开关、不改密钥/协议或当前运行服务。

## 新行为

PC1.4.0-rc2起推荐 `eyepqc run --dev-usb-bootstrap`，默认身份为当前用户应用目录
`LOCALAPPDATA/EYEPQC/pc/data/private/board-test-identity.bin`。
路径从既有 `cli_settings.settings_path().parent` 派生，不依赖工作目录或EXE位置，不扫描文件。
`--dev-identity-file <其他受保护文件>` 仍支持覆盖，但不给开发态开关就拒绝。
普通run不解析/读取开发身份、不启动bootstrap；READY仍只QUERY核pin，不为默认参数预读SK。
WAIT实际需要私钥时沿用原ACL/长度/内嵌公钥/H(ek)/应用pin检查；不生成新身份，不把私钥放进配置或EXE。

## 软件与产物

- 新测试在旧版先失败2处；修后bootstrap19项/4.043秒、CLI12项/1.040秒、settings11项/7.752秒通过，无skip。
- CLI/settings两组使用新冻结EXE及隔离配置，未访问实际身份/USB；主协调独立复跑bootstrap19项/3.957秒通过。
- 新EXE的9个自有模块code object与当前源码一致，ZIP14成员/CRC/源文件一致检查通过。
- CLI：10,291,769字节，SHA256 `385977a4790bcb2240788b11c9b21e74439dcdf995d79b35f5d86cbbc1ad30be`。
- 安装器：12,132,907字节，SHA256 `d5d8f9379a52ebc2383b22516976e04cac9ad551426ebfd1afea5dfdbfbcaa19`。
- 包：`build/releases/pc-1.4.0-rc2/EYEPQC-PC-1.4.0-rc2-windows-x64.zip`，21,690,984字节，
  SHA256 `762f7f7fd156fe58c0371bdaebaecf852f0d8243ecce15f4077730675295811f`。
- 原rc1及四端候选包保持不变，新包用户验收pending；没有实际安装，也没有重启正常播放的服务。

## 用户升级

在用户原Windows环境正常停止旧服务后，运行新安装器，默认program-only保留现有配置和材料。
不要在Codex重定向AppData视图中安装后就认定用户终端已升级；原终端用 `eyepqc --version` 确认1.4.0-rc2。
确认版本后使用简化命令，老版本仍需原显式路径；当前服务继续正常运行，不强行替换进程。
本次没有重新验证手机/视频/板端首连门禁，不能把参数回归当新硬件验收。
