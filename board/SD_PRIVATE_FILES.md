# 三份 SD 私有文件：EYEKEY.BIN、EYERNG0.BIN、EYERNG1.BIN

板卡从 SD 启动时，除了 `BOOT.BIN`，卡根目录还需要三份**私有文件**。它们不随发布包分发，也不进入 BOOT、Git、日志、手机或服务器。
本页只讲怎么准备和核对；写卡、接线、上电见 [开发板安装与使用](DEPLOYMENT.md)。

| 文件 | 大小 | 内容 | 能否重新生成 |
|---|---|---|---|
| `EYEKEY.BIN` | 1632 字节 | ML-KEM-512 身份私钥（含 800 字节公钥段） | 能，但公钥指纹会变，手机须重新配对 |
| `EYERNG0.BIN` | 80 字节 | 随机状态槽 0：`EYERNG01` + 大端 64 位代号 + 32 字节秘密 + SHA256 | 每次准备都会新建；**不能**从旧卡恢复 |
| `EYERNG1.BIN` | 80 字节 | 随机状态槽 1，初始与槽 0 同为第 0 代 | 同上 |

格式与故障规则见 [SD 固定身份与持久随机状态](../doc/g6_sd_identity.md)。

## 先做判断

| 你的情况 | 怎么做 |
|---|---|
| 卡上已经有这三个文件，且能正常看视频 | **不要重新生成**。升级只换匹配的 `BOOT.BIN`，保留这三个文件。 |
| 有旧卡/旧电脑上的身份文件，想保持手机指纹不变 | 走[方案 A](#方案-a复用旧身份推荐) |
| 全新部署，没有历史身份 | 走[方案 B](#方案-b全新身份)，并重新配对手机 |

判断方法：卡根目录能看到 `EYEKEY.BIN`、`EYERNG0.BIN`、`EYERNG1.BIN` 三个文件（不是压缩包，不在子目录）。
只要已存在任意一个，就停下来核对，不要点“全部替换”。

## 准备环境

- 在**仓库根目录**执行，`./.venv` 已按 `requirements.txt` 装好（工具依赖 `kyber-py`、`cryptography`）。
- 只用可信电脑；配置端会接触私钥，可能保留副本，这属于已知边界。
- 输出目录必须是**尚不存在**的本机绝对路径，父目录已存在；工具拒绝覆盖、拒绝链接路径。
- 失败时保留现场，换一个新目录重试，不复用失败目录。

## 方案 A：复用旧身份（推荐）

适用于已有部署、或手上有旧身份文件的情况。身份不变，手机和 `pairing.json` 都不用动。

```powershell
$Prepared = Join-Path $env:LOCALAPPDATA 'EYEPQC/sd-identity-1'
$Existing = Join-Path $env:LOCALAPPDATA 'EYEPQC/pc/data/private/board-test-identity.bin'
& ./.venv/Scripts/python.exe board/prj/prepare_sd_identity.py --output "$Prepared" --identity-file "$Existing"
```

- `--identity-file` 也可以指向从旧卡复制出来的 `EYEKEY.BIN`（1632 字节），效果相同。
- 成功标志：退出码 0，并输出 `"status": "SD_IDENTITY_PREPARED"`。
- 核对：`$Prepared/public/public.sha256` 应与现有 `pairing.json` 里的公钥指纹一致；不一致就不要写卡。

## 方案 B：全新身份

仅在没有历史身份、或明确要换新身份时使用。**公钥指纹会改变，手机必须重新完成可信配对。**

```powershell
$Prepared = Join-Path $env:LOCALAPPDATA 'EYEPQC/sd-identity-2'
& ./.venv/Scripts/python.exe board/prj/prepare_sd_identity.py --output "$Prepared"
```

然后重建配对信息（示例地址必须换成实际可信 WSS 地址）：

```powershell
& ./.venv/Scripts/python.exe pc/src/host/prepare_pairing.py `
  --identity-dir "$Prepared/public" `
  --endpoint wss://203.0.113.10:8765/stream `
  --config-file "$env:LOCALAPPDATA/EYEPQC/pc/data/public/pairing.json"
```

手机端需要接受新指纹；旧指纹不清除会一直报配对/指纹错误。不要为了让旧指纹“过”而换回旧身份。

## 核对产物

`$Prepared` 下的结构：

| 路径 | 用途 |
|---|---|
| `private/EYEKEY.BIN` | 复制到卡根目录 |
| `private/EYERNG0.BIN`、`private/EYERNG1.BIN` | 复制到卡根目录 |
| `public/public.bin`、`public/public.sha256` | 配对用公开材料，**不**放到卡上 |
| `identity.json` | 公开状态与安全边界记录，**不**放到卡上 |

快速核对：

```powershell
Get-ChildItem "$Prepared/private" | Select-Object Name, Length
```

应为 1632、80、80 字节；两个状态文件此时内容相同（都是第 0 代），上板运行后会各自变化。

## 复制到卡

1. 手机点“停止”，电脑服务窗口按 **Ctrl+C**。
2. 关闭板卡 **K1**，确认核心板灯全灭，再取卡；不要带电拔卡。
3. 读卡器接电脑，核对盘符、容量与 FAT32；不格式化、不照抄旧盘符。
4. 先备份旧 `BOOT.BIN`，再放入新的 `BOOT.BIN`。
5. 把 `private/` 下的三个文件复制到**卡根目录**，等待完成。
6. 安全弹出，整只读卡器拔下再插回，确认四个文件都在根目录、大小正确。

详细步骤和读回核对见 [开发板安装与使用](DEPLOYMENT.md#2-写卡已有正常运行卡跳过)。

## 不要做

- 不要把旧卡的 `EYERNG0.BIN`、`EYERNG1.BIN` 备份恢复到新配置；状态代号/链会不匹配，板卡会拒绝会话。
- 不要克隆运行卡给第二块板同时使用。
- 不要覆盖卡上已有的三个文件；不要反复“全部替换”或格式化。
- 不要把三份文件提交 Git、发到聊天/日志、放进公开配对 JSON 或发布 ZIP。
- 运行后状态文件变化是正常的，不要再拿它和初始文件逐字节比较。

## 故障对照

| 现象 | 原因与处理 |
|---|---|
| `SD_IDENTITY_ERROR` | 输出目录已存在、路径含链接或依赖缺失；换新目录，检查 `.venv` |
| 大小不是 1632/80/80 | 复制不完整或文件被截断；重新从 `$Prepared/private` 复制 |
| 板卡停在安全会话错误 | 状态槽缺失/损坏/代号不合法；不要回退旧槽，按故障恢复重新生成独立状态 |
| 手机提示指纹/配对错误 | 身份换了但没重做配对，或手机仍存旧指纹；按方案 B 重新配对 |

## 相关文档

- [开发板安装与使用](DEPLOYMENT.md)：写卡、接线、上电、日常连接
- [开发板进阶部署](DEPLOYMENT_ADVANCED.md)：构建固件、准备身份、打包、观测
- [SD 固定身份与持久随机状态](../doc/g6_sd_identity.md)：文件格式、状态推进与安全边界
- [Windows PC 部署](../pc/DEPLOYMENT.md)：账号、TLS、配对与 `eyepqc run`
- [v1.1.0 发布说明](../doc/releases/v1.1.0.md)：本版交付范围与限制
