# EYEPQC FPGA 工程复用指南

适用范围、可复用案例、验证结果与失效边界见同目录 [README.md](README.md)。

## 目标

在 Zynq-7000 上按证据驱动方式构建、仿真并验证 JPEG 采集与 AES-GCM 加密工程。默认工具根目录由 `EYEPQC_TOOL_ROOT` 指定；Vivado/Vitis 版本、目标 part、板卡版本都要按当前机器和硬件重新核对。

## 工作流程

1. 检查 `git status`，确认工作树中已有改动；不要覆盖或清理用户文件。
2. 先运行受影响模块的离线仿真和主机参考测试，再运行 Vivado 综合/实现。
3. 用 `build_manifest.json` 中的源文件和产物哈希核对构建；核对器件 part、DDR 符号范围、时序和 DRC。
4. 只有目标板型、DDR、电源、摄像头接口与约束匹配后才下载。首次板测使用 JTAG 临时加载；没有明确要求时不写 SD、QSPI 或 Flash。
5. 记录运行日志、结果 JSON、帧率、丢帧、溢出、认证解密和图像解码结果。保留失败尝试，不以重跑后的成功结果掩盖原因未明的失败。
6. 汇总时区分：离线参考、RTL 仿真、综合/实现、板端实测和整机验收。任何层级都不能替代下一层的证据。

## 项目入口

- 规则与阶段依赖：`doc/steps.md`
- 构建/板卡输入：`board/README.md`、`prj/`
- 主机测试：`sim/tb/`；提交钩子：`.githooks/pre-commit`
- 当前证据和未完成项：`report/progress.md`、`report/competition_submission.md`
- G3 首次 JTAG 验收：`report/pc_build.md`

## 结果口径

- XSA 的 Zynq 型号相符不等于底板引脚、DDR 参数、摄像头模组和电气条件相符。
- 用户约束时序满足和 DRC 零告警不是一回事；逐条保留未消除告警及影响。
- 历史板测、仿真、bitstream 完成提示和本次板卡运行结果分别记录。
- 开发密钥、JTAG 注入私钥/种子和测试 VID/PID 不作为产品级安全方案。
- 比赛规则或评分细则缺失时，不猜测模板或验收标准；先把工程本身的可复现证据准备齐。
