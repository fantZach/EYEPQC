# 软件阶段交付记录

更新：2026-10-06。本记录覆盖当前电脑端软件，不替代整机门禁。

## 本轮修正

- 修正 G3 的 DMA 配置查询：经典 BSP 使用 `XAxiDma_LookupConfigBaseAddr`，SDT 使用基地址查询。
  UART 同样区分经典设备 ID 与 SDT 基地址；真实生成的 AMD 配置表在 PC 上验证 UART、两路 DMA 和 USB 查询。
- 经典 BSP 使用 `xtime_l.h`，SDT 保留 `xiltimer.h`；USB 中断分别使用经典 GIC 配置或 SDT 原生封装。
- USB 库构建只保留使用的探针缓冲和函数，使 G3/G4/G5/G6 均可在 `-O3 -Wall -Wextra -Werror` 下编译。
- 用 `prj/build_software.py` 与 `prj/generate_bsp.tcl` 固化 HSI/BSP/ARM GCC 构建过程，解决此前仅有手工构建记录的问题。
- G6 启动前核对应用清单；`--verify-only` 只检查文件，不读开发私钥，不接触板卡。
- G4/G5/G6 帧率计时改用高精度 `perf_counter`，修复多帧落在同一 `monotonic` 计时刻度时除零的问题。
- 增加根目录 `run_demo.ps1`，统一电脑检查、构建、开发素材准备、预检和用户实机入口。

## 构建与验证

当前交付：`build/vitis/software_ready/`。同一 XSA 下四个 ARM ELF、匹配 FSBL、四份 `BOOT.BIN`
均已生成。BSP 编译 129 个源文件；FSBL 的 PS 初始化与 XSA 完全一致，ELF 的加载段位于 OCM；
Bootgen 已回读镜像，确认 FSBL→bitstream→应用的分区组成。所有启动介质仍未写入。

`software_verification.json` 记录四个应用共 90 项源文件/XSA/二进制哈希检查，另核对 710 项
生成 BSP、FSBL 和编译命令输入；真实 AMD 配置表查询通过。四个应用均保持 `board_validated=false`。
供应商 FSBL 生成日志保留 `Hsi 61-10` MSS 兼容提示；当前没有开启 RSA Secure Boot。

完整电脑回归由 `prj/check_software.py` 执行，包含依赖固定版本、向量一致性及 M00、AES MVP、
M01～M05、M07～M10、M12、G3、G5、G6 共 17 个检查入口。
日志与机器可读结果见 `build/software_checks/final_goal/`。
最终结果为 **17/17 PASS**，累计检查耗时约 223 秒；所有检查均为电脑端范围。
原先受工具环境影响的 M04/M05 原生 XSim 本轮已通过；默认 GCC 本轮可以正常启动，
没有替换 XPM 模型、忽略断言或放宽用例。

G6 新增 3 项内存 USB 集成测试：真实 C ML-KEM/会话代码与 Python 主机互通；
20 次新鲜握手/换钥、软件 JPEG 分片认证、密钥清零、坏 Finished、坏 Tag 和重放拒绝。
JPEG 是合成图片，GCM 是软件参考，USB 是内存分片流，不能作为摄像头、PL GCM 或物理 USB 验收。

## 当前停止位置

下一项为用户首次实机 G3 验证，具体接线、命令、成功标志和日志路径见
[首次实机指南](../doc/bringup.md)。G3 通过后再运行开发态 G6。
本轮没有连接 JTAG、运行硬件服务、下载固件、读写板卡内存或写入启动介质。

G0 冷启动/LED、G7 物理故障与 2 h 长测、去 JTAG 密钥注入、板端 TRNG/DRBG、
Keccak/SHAKE FPGA 加速及最终比赛演示界面仍是后续工作；不由本轮软件验证宣告完成。
