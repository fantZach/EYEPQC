# EYEPQC FPGA 工程复用 Skill

本 Skill 为 Zynq-7000 / Vivado / Vitis 工程提供一套证据驱动的构建、DMA/DDR、时序和板级验收流程。它源自 EYEPQC 的实际工程案例，适合在相近的 FPGA/SoC 工程中复用检查方法；具体器件、BSP、时钟、缓存属性和 USB/DMA 驱动必须按目标平台重新核对。

## 何时使用

- 修改 RTL、PS 固件、USB、摄像头或 DMA 缓冲区后，需要决定先做哪些离线和板级检查。
- 需要证明 ELF、XSA、bitstream 与源文件属于同一个构建身份。
- 需要审阅 Vivado implementation timing，区分“成功生成产物”和“时序闭合”。
- 需要整理失败、复测和硬件操作证据，避免把局部通过写成整机验收。

## 建议流程

1. **保留当前状态。** 在改动前查看 `git status`、分支和最近提交。保留用户已有修改；不要用清理或重置操作代替理解工作树。
2. **先跑离线验证。** 按改动范围选择单元测试、RTL 仿真、主机协议测试和固件编译。记录工具版本与失败，不以综合成功替代功能验证。
3. **核对构建身份。** 使用项目 manifest 验证脚本对源输入和产物做 SHA-256 核对，再核对器件 part、匹配 XSA/BSP 和候选 manifest。`board_validated=false` 是构建状态，不得由哈希通过自动改成 `true`。

   ```powershell
   .venv\Scripts\python.exe pc/src/host/g6_board.py `
     --workspace build/vitis/g6_secure_cleanup_20261011_candidate012_tx_ownership_r3 `
     --verify-only
   ```

   示例输出：`G6_PREFLIGHT_OK hashes=197 board_accessed=false`。该命令只验证文件，不连接板卡。

4. **审阅实现时序。** 阅读与目标 XSA 对应的 implementation timing summary，确认 WNS、WHS、TNS、THS 和 failing endpoints；记录报告对应的构建身份。仅凭 bitstream 存在或工具返回成功不能判定时序闭合。
5. **处理 DMA/DDR 所有权。** 先确认每个 buffer 的生产者/消费者和缓存属性，再按该驱动的 DMA 方向、对齐、缓存行和完成语义安排 flush/invalidate 与内存屏障。检查数据 buffer、guard 和描述符等元数据的所有权交接；CPU 只有在设备完成并完成必要的 cache 同步后才读取数据。项目实例位于 `board/src/ps/src/camera_dma.c` 与 `board/src/ps/include/usb_recovery.h`。这些例子不能直接替代目标 BSP/驱动文档。
6. **分层安排板测。** 先跑单次、可恢复的基线，再跑具体故障单轮；单轮通过后才进入重复批次。写明是否下载 JTAG、是否有断电或物理拔插、是否写入 SD/Flash/eFuse。失败保留在汇总中。
7. **报告限制。** 把主机应用层接收、USB 控制器完成、设备端 dTD 完成和帧认证作为不同证据。对照同构建的正常基线有助于缩小故障范围，但不等于故障场景通过。

## 已验证案例

| 可复用方法 | 本项目证据 | 结果与边界 |
|---|---|---|
| 构建哈希预检 | candidate012 r3，`pc/src/host/g6_board.py --verify-only` | 197 项检查通过，工具报告 `board_accessed=false`。这证明选定输入/产物与 manifest 一致，不证明板测通过。 |
| implementation timing 核对 | `report/keccak_sponge_x4_capture_fix_20261011.md` 的独立 KX41 候选 XSA | fully routed，WNS `+0.029 ns`、WHS `+0.082 ns`、失败端点 0。只适用于该独立候选，不能外推到视频工程。 |
| 设备端与主机端分层诊断 | `report/g7_candidate012_tx_ownership_board_20261011.md` | receiver-exit 单轮中 51 字节 EP1 IN dTD 报告完成而主机 39 次读取仍为 0 字节；同构建普通 CDC 重连后认证 141 帧。故障根因仍未知，不能把 dTD 完成或普通重连当成 G7 通过。 |
| DMA/DDR 所有权审阅 | `board/src/ps/src/camera_dma.c`、`board/src/ps/include/usb_recovery.h`；受控恢复证据见 `report/g7_candidate006d_acceptance_20261010.md` | 源码中的缓存维护与受控故障恢复记录可作为审阅案例；不能代替新板型上的缓存一致性测试，也不能外推到未测的 DMA 错误场景。 |

## 复用时的输入与输出

调用者应提供仓库根目录、目标 board/part、Vivado/Vitis 与 BSP 版本、候选构建目录、验收判据，以及允许的硬件操作范围。执行后应留下：命令、工具版本、源/产物 hash、timing 摘要、原始结果路径、失败轮次、硬件操作记录和明确的证据边界。

## 失效条件与安全边界

- 构建目录已移动、manifest 来源不明或源文件变更后，旧哈希结果失效。
- 更换 FPGA part、板卡版本、DDR、摄像头、BSP 或工具版本后，旧板测不能直接背书新目标。
- DMA 方向、buffer 可缓存性、缓存行大小或驱动完成语义不同，必须重做缓存所有权分析；不要机械复制缓存 API 顺序。
- 设备端发送返回成功、dTD completion、`READY` 状态、USB 枚举和用户态收到/认证数据是不同层级，不能相互替代。
- 本 Skill 没有在独立团队/干净仓库完成迁移性评估；当前案例证明它与本仓库的文件和报告相符，不证明对任意工程都可直接套用。
- 涉及 SD/Flash/eFuse 写入、公开仓库、许可证选择或密钥时，须先确认权限、目标和材料来源；不得把测试密钥或私有原始数据放入交付包。

## 在本仓库复核

- 构建身份：`pc/src/host/build_manifest.py`、`pc/src/host/g6_board.py --verify-only`
- DMA/缓存：`board/src/ps/src/camera_dma.c`、`board/src/ps/include/usb_recovery.h`
- 时序检查：`board/prj/keccak_sponge_x4_system_build.py`、`board/prj/keccak_sponge_x4_firmware_build.py`
- 验收口径：`report/acceptance_matrix_20261009.md`
