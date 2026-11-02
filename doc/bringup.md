# 启动与开发检查入口

当前版本使用 SD 本地身份启动，完整步骤见 [四端部署教程](deployment/README.md)。
板卡从 SD 加载 PL 配置与 PS 程序，Windows PC 启动转发服务，Android 登录后播放。

## 日常启动

确认 SD 上的启动程序、固定身份和持久随机状态已按 [板端教程](../board/DEPLOYMENT.md) 配置。
板卡上电后，在已完成配置的 Windows 终端执行：

```powershell
eyepqc check
eyepqc run
```

手机填写已部署的服务地址及账号，连接后查看认证帧和画面更新。
配置与维护分别见 [PC 教程](../pc/DEPLOYMENT.md) 和 [Android 教程](../mobile/DEPLOYMENT.md)。

## 开发检查

下列命令从源码仓库根目录执行，使用已安装依赖的 `.venv`：

```powershell
& ./.venv/Scripts/python.exe board/prj/check_dependencies.py
git hook run pre-commit
```

完整离线回归入口为 `board/prj/check_software.py`，需要匹配的 AMD 工具、GCC 和 Icarus。
它输出各项日志与结果摘要，适用于修改硬件接口或密码模块后的开发回归。

SD 固件构建使用 `board/prj/build_software.py --g6-sd-identity`，产物预检使用
`board/prj/verify_software.py <构建目录>`。工具版本、XSA 与构建参数见
[SD 身份说明](g6_sd_identity.md) 和 [板端进阶教程](../board/DEPLOYMENT_ADVANCED.md)。

## 历史开发入口

早期 `run_demo.ps1` 及 `run_g7_*.ps1` 服务于旧 JTAG 演示和故障批次，现已移除。
历史 G3/G6 报告保留当时的测试结果；当前部署入口以上述 SD 流程为准。
