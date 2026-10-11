# 电脑端完整回归记录

日期：2026-10-11。执行入口：`run_demo.ps1 -Mode Check`。回归基于源码提交 `bb212bc5a134228e6fed7223331bc9e2c2c2063a`，Python 3.12.13、GCC 13.1.0 MinGW-w64 和 Vivado 2026.1。共 19 个顺序门禁，19/19 通过；逐项耗时合计 229.672 秒。运行器机器结果标记 `board_accessed=false`，本轮没有查询或操作板卡。

覆盖依赖和向量一致性、M00、AES MVP、M01–M05、M07–M10、M12、G3、G5、G6、USB recovery 与演示回归。M04/M05 使用原生 XSim 仿真。结果不包含独立完整 Vivado/Vitis 工程重建、candidate014 上板、G0 启动、G7 物理 USB、生产密钥或全域清零验收。

机器可读的脱敏摘要在 [JSON 记录](software_regression_20261011.json)。完整运行日志留在本机忽略目录 `build/software_checks/20261011_122413_246856/`；原始 `result.json` SHA-256 为 `2d2b2cfdf17ab1a80983474bbfa034644c9c73da07fc4795bc7933963a32c5bb`。仅摘要纳入 GitHub 审阅材料，原始日志未公开。

这次回归更新了此前 `report/software_ready.md` 中的 18/18 旧记录；历史记录仍保留并标记日期，不把电脑端 PASS 扩展成板级通过。
