# Keccak 身份缓存优化版实板基准 — 2026-10-10

优化版固件在三轮实板 HW 运行中均完成逐次 tcId 76 校验；同一启动内的硬件路径仍比软件慢。本次不集成到正式 006d 视频构建。最终 006d 恢复结果通过，恢复证据与 Keccak 性能窗口分开记录。

## 构建和核验

构建目录为 `build/parallel_20261010/C/firmware_identity_cached_retry2_elfs`。manifest SHA-256：`29e42e78ef8c0057d6c21906059c2f956969d92451e5581a50c3144cff35a72e`；HW ELF SHA-256：`bdd275ead88a795ed88dcfabf5ad44cf6cc0ec3e220e31590f463ef199015b32`；SW ELF SHA-256：`2e38b1777df1b6801493a31e0a17878ebd29f0cda661ea516ac0c1095f3c135c`；XSA SHA-256：`70fe149c62b3a2cc402adfb78fac625520151309015d89815576784a1fd250a2`。manifest 标记 `board_validated=false`，板上结果由本报告中的采集记录单独证明。

已独立重算 manifest 中的 **715** 项源码、BSP 输入、vendor 输入、生成头文件、库、ELF、map、readelf/反汇编和 XSA 哈希；三次 capture 各自也报告 715 项核验，并绑定同一 manifest、HW ELF 和 XSA。实测 `counter_hz=333333343`，与 BSP CPU 时钟 `666666687` 的一半向下取整相符。

Windows 深路径 BSP 生成首次在 260 字符目标路径处失败，没有产生 manifest。最终构建经临时 `P:` 映射到仓库根后，写入新的 repo-relative `build/parallel_20261010/C/firmware_identity_cached_retry2_elfs`；独立校验的是此最终目录。参数错误产生的根级临时输出已移到 `build/failed_build/keccak_identity_cached_wrong_repo_relative`，不用于本报告。

## 同一启动内的三次解封装比较

每行的 SW 与 HW tick 均来自同一次 `firmware_hw` 启动，各窗口均完成 3 次完整 ML-KEM-512 解封装。比值为 SW ticks / HW ticks，小于 1 表示 HW 更慢。

| Run | SW 3 decaps (ticks) | HW 3 decaps (ticks) | SW/HW ratio | HW slower | Timeout fallback (ticks) |
|---|---:|---:|---:|---:|---:|
| hw_identity_cached_01 | 1074148 | 1164250 | 0.922609 | 8.39% | 1417320 |
| hw_identity_cached_02 | 1073007 | 1164108 | 0.921742 | 8.49% | 1416105 |
| hw_identity_cached_03 | 1073817 | 1163544 | 0.922885 | 8.36% | 1417510 |

三轮 ratio 均值 **0.922412**，范围 **0.921742–0.922885**；HW 慢幅均值 **8.41%**，范围 **8.36%–8.49%**。三轮正常 HW 窗口均为 96/96 hardware、0 fallback；timeout 窗口均为 96/96 fallback，`timeout_clear_status=00000000`。

## 计时和正确性范围

每次 backend configure 都在计时前重新读取并核验实际 ID/version。配置失败只走软件 fallback，不写 STATE、不发 START。通过核验的每个三次解封装窗口各输出一次 `HARDWARE_CONTEXT_IDENTITY_PASS`；每轮两次，分别对应正常 HW 与 timeout 窗口。优化点是每次 Keccak permutation 不再重复读取 ID/version；所有三个窗口的比较均在同一 `firmware_hw` boot 内。

本版在 SW、HW 和 timeout 三个窗口中，**每一次**解封装返回后都会与 tcId 76 期望共享密钥比较，三次比较都计入各自计时。每个窗口输出 `KAT_PASS iterations=3 tcId=76`。因此这些窗口比历史基线多计入逐次 32-byte 比较开销。身份读取在计时外；完整解封装计时包含路径分派、STATE/RESULT MMIO、START 和 bounded STATUS polling。

相较历史报告中平均 HW 慢 8.62%，本版平均慢 **8.41%**。不能把这约 0.21 个百分点的观察差值完全归因于身份读取缓存：历史基线仅在窗口结束后核对最后一次共享密钥，本版则在计时内逐次核对三次结果；身份核验与 KAT 计时口径都发生了变化。

timeout 范围仅验证 STATUS 清零，不读取 STATE/RESULT，不宣称全设备 zeroize。板上重复的是一个 tcId 76 向量，不是完整 84 向量集合。当前三轮都显示硬件端到端仍较慢，因此不集成进正式视频固件。

## 006d 恢复

Keccak 实验后，root 使用冻结快照 `build/restoration_source_b83ee4e` 恢复最终 006d，结果 `passed`；恢复前完成 180 项来源哈希预检。一次较早恢复因本地 ignored 开发输入 `public.bin` 缺失，在 JTAG 前以 `FileNotFoundError` 退出；补齐快照内输入后重试通过。恢复采集到 **140 帧**、**1403801 bytes**，窗口 **2.9231648 秒**、**47.55 fps**，board counters 为 null。恢复 manifest SHA-256：`0eb922b903f4f87b555a09cce67e928d5a910a37ece3ba359aebe055ffe28abc`，ELF SHA-256：`e93ad4b6551bb993821a8e396d8f4c4c1f40c6bd6292247391ff129a0d9e8051`，XSA SHA-256：`46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024`。结果和首末帧 SHA-256 见 JSON；报告不包含会话标识、密钥或指纹。主工作树当前 G6 源不作为旧冻结构建的来源匹配声明。

## 证据文件

三轮 capture、UART 原文和 JTAG stdout/stderr 的仓库相对路径及 SHA-256，完整原始 tick、dispatch、KAT marker 与恢复来源均记录在 [`keccak_identity_cached_20261010.json`](keccak_identity_cached_20261010.json)。历史 safe 基线继续保留在 [`keccak_board_benchmark_20261010.json`](keccak_board_benchmark_20261010.json)，未覆盖。
