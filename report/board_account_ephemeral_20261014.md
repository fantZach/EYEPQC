# Board：稳定身份与临时 ML-KEM 业务 profile

2026-10-14。按用户授权完成代码、离线测试和 ARM 构建；本轮仅 software validation。
未操作 JTAG、COM4、板上 SD、Flash/eFuse，未加载新固件或写真实私钥。
冻结字节契约由主协调维护 `doc/account_ephemeral_protocol.md`；账号/WSS/UI 由 PC/Android 项目负责。

## 实现

- `protocol.c/.h` 支持明确的 suite2 HELLO/ACK 和 type10 offer864B/type11 reply832B body。
  身份 bootstrap 沿用固定公钥 pin、KEM、HKDF 与双向 Finished；HELLO/ACK suite 必须一致。
- `ephemeral.c/.h` 执行真实 ML-KEM-512 KeyGen/Decaps，校验冻结 MAC 域及 bootstrap transcript，
  以临时 KEM shared32 和新的完整业务 transcript 派生业务 key；不将 bootstrap key 用于视频。
- 临时状态与原 192B `eye_session` 分离；成功解封装后清临时 SK/offer、局部 shared/MAC/hash 缓冲，
  替换并清旧业务 key、计数器归零，再执行新双向 Finished，最后接受 START。
- `g6_usb.c` 拒绝提前 START、重复/错方向/错阶段的记录；清握手缓存时同步清临时状态。
  首次 HELLO 至 START 总期限 15 秒；suite2 视频会话 START 后 1800 秒硬截止，
  清旧 session/DMA/GCM/USB 后进入 WAIT_HELLO，只有完整新握手能恢复业务。
  手机按主协调约定于 1785 秒提前发起重建，板端硬截止没有放宽。
- 新记录错误及握手超时走现有 fail-closed；断线、故障及清理失败均覆盖临时状态。
  suite1 只作为明确的开发兼容保留，生产 profile 拒绝 suite1，不静默降级。
- Dev coins 来自既有 PC/JTAG seed 加单调 counter 的 HMAC；Production coins64 直接来自已有
  `g6_production_entropy_bytes`，失败清输出并停流，不使用开发 seed 回退。
  稳定身份私钥继续只由 production provider 解封装接口使用、不返回 application；
  临时私钥由 application KeyGen 生成并仅保存在 RAM，二者不是同一个存储边界。

M09 的 deterministic KeyGen API 已启用，随机 API 仍禁用。所有引用正式 G6 的构建入口、
camera fault/auto recovery 变体的源列表和哈希输入同步纳入新模块。
新固件清单记录 supported suites、临时 SK RAM 存储及 coins 来源；没有提供或认证生产熵/身份 provider。

## 新 ARM 产物及追溯修正

最终目录：`build/vitis/g6_account_ephemeral_20261014_2`。
复用匹配的历史 `build/vivado/g4_usb_1/m01.xsa` 及内置 bitstream，未重新实现 PL。

- G6 ELF：`g6_usb/build/g6_usb.elf`，SHA-256
  `b794a2da57385d0473c86bcb512cf53fd0bfdf6ec5a1427766d2b443861d7a36`。
- 新目录从当前源码生成 BSP、USB bounded overlay 和 ARM ELF；启动 map 验证通过。
- `verify_software.py` 完整通过：75 项固件清单哈希、真实生成 BSP 的 lookup 和 standalone startup。
- `board_validated=false`，没有生成/部署 G6 SD BOOT.BIN，G6 自主密钥/熵源仍未落实。

旧 `software_build.json` 将混合来源的 `external_sources` 都编成不存在的
`<app>/external_sources/...` 路径，导致完整追溯检查失败。
现构建时区分真实 workspace overlay 与安装 SDK driver，确认每个实际文件及摘要一致后记录绝对路径，
验证器逐个重算这些摘要。没有改旧产物摘要，也没有跳过外部源码验证。
早期 `_1` 产物生成后构建脚本再加入清单字段，最终应使用 `_2`，不能绕过旧清单对脚本变化的拒绝。

## 验证与 fixture

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s board/prj/tests -p 'test_ephemeral*.py' -v
.\.venv\Scripts\python.exe board/prj/verify_software.py build/vitis/g6_account_ephemeral_20261014_2
```

5 项自身测试通过（含边界 subtests）：

- Portable C 真实 KeyGen/Decaps 与已有 PC Kem Encaps，独立 Python HMAC/HKDF 校验。
- 完整二次 Finished/START、bootstrap video 清零、业务 key 与计数器替换；临时状态成功后全零。
- 错 MAC/TH/长度/方向、重放 reply、重复 offer、suite mismatch 拒绝并清敏感状态。
- 真实 `g6_usb.c` 静态函数在 SDK mock 下验证：提前 START、二次 Finished、
  15/1800 秒前一 tick 与截止 tick、到期后新 HELLO，以及断线/FAULT 清临时 SK。
- Production mock 验证 suite1 无 ACK、provider64B coins 路径、部分输出失败时清零、无开发回退。
  Mock 只证明分支行为，不能算真实 provider/熵源验收。

共享原 G6 cleanup/production harness 也重新通过；四项 Git hook 保持 M00/M10/M12/G5。
主协调和 Android 分别负责跨 C/Java/WSS 联测，手机及实板结果不从软件测试推定。

公开 fixture：`board/output/account_ephemeral_fixture_20261014/fixture.json`。
所有值为公开 KAT/固定合成 coins 的测试材料（`test_only=true`），无真实身份私钥。
含 hello/ack/identity_kem、公钥、bootstrap shared/TH/key/Finished、offer/reply、
keygen/encaps coins、business shared/TH/material、business Finished/START；二进制字段均 hex。
生成入口为 `board/prj/tests/test_ephemeral.py`。

## 限制

开发态 PC 已知 seed，能重建临时 SK，不能声称对 PC 具有前向保密。
Production provider 的真实熵、长期身份安全保存、secure boot/JTAG 防护仍待实施；
本次没有新增真实 provider、SD 私钥保存、硬件熵源、多 viewer 或账号后台。
新协议尚未完成形式化安全证明、实板/手机新版本验收或独立视频 SD 启动。
