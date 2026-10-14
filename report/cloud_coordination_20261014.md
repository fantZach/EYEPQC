# 四端公网中转代码协调

用户要求先完成各端代码；server 新建独立文件夹及聊天。
当前采用 OpenSSH 反向 TCP 中转，接口见 `doc/cloud_relay_plan.md`，不继续推进 P2P。

## 聊天与文件所有权

- Server `01a139bf-a174-7793-9cf4-3163a2358a4a`：`server/`、独立 server 报告。
- PC `01a133d0-8ab9-7902-b71f-de040f111737`：`pc/`、独立 PC 报告。
- Android `01a133d0-8655-7961-918e-cc594d043089`：`mobile/`、独立 mobile 报告。
- Board `01a133d0-8218-7e12-b5c4-9a9eef0801ff`：`board/`、独立 board 报告。
- 主聊天：共享 README/doc/steps/progress、跨端软件联测、统一 Git 提交。无新增 worktree/submodule。

本轮禁止各聊天操作硬件、云端、代理或运行服务，实际部署等用户提供云实例条件后另行验证。
四聊天共用工作目录和 Git index，因此停止各端单独 stage/commit，改由主聊天统一完成；不撤销他人更改。

## 主聊天透明 TCP 回环验证

新增 `sim/tb/test_cloud_passthrough.py`，复用 `test_account_three_end.py` 的真实 C/Java suite2 软件测试。
一个 raw TCP 转发节点不解析/解密 TLS、账号或内层记录，只以有界读块和流背压转发字节。
客户端保留受信任临时 CA/主机名校验；后端是真实账号 WSS relay，USB/摄像头为模拟器，密码与KAT均为公开测试夹具。
实际五窗口 normal/rekey/timer/stop/normal 均通过，耗时13.952秒；检查双方 Finished、临时KEM派生、
完整认证解密/JPEG哈希、新临时公钥、STOP释放模拟USB和下一连接。上下行TCP字节计数均大于零。
normal/rekey/timer的既有客户端主动abort产生WebSocket1006，relay对应记录1011并完成清理；
显式STOP窗口为code1000/stop_forwarded1/errornone。前者不改写为正常STOP，也不当成隧道认证失败。

此验证不是实际SSH连接、Linux sshd执行、云端、真实Android、实板或公网吞吐证据。
只证明在现有账号/suite2/WSS链路前加入透明TCP节点仍能互操作。
各端准确测试和未执行项由独立报告补充，不把源码兼容或host配置生成当部署通过。

主聊天再次执行TCP五窗口通过（13.372秒）和原直连WSS五窗口通过（17.175秒）；
PC全量42项通过（36.904秒）、Server16项通过（0.137秒）；Android核心160/JSON52/临时KEM37及四个TLS/接管回环均通过。
Board聊天报告本轮36项离线及M10通过；其准确命令/首次入口错误/历史边界见 `board_cloud_20261014.md`。
PC真实OpenSSH `-G`仅是离线配置解析；Server未有真实Linux sshd，不能据生成/静态校验标部署通过。

## 安全和待办

TLS证书SAN必须为手机访问的云地址；SSH host key需可信来源独立核验。
云端只配置专用隧道SSH公钥，不上传PC CA/TLS私钥、板端身份、seed或账号材料。
手机账号与强scrypt哈希仍留PC，现有0.6 APP无需引入SSH或为新地址改变信任链。
实际云端Linux配置、校园网SSH可达性、公网WSS、视频/换钥/断线与吞吐都另行验收。
此前QueueFull和P2P失败不被本次软件PASS覆盖，完整G8/G9及视频SD自启动/生产安全仍未通过。
