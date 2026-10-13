# Android 会话清理与 SD 启动接入（2026-10-13）

范围：仅 mobile 源码、测试、README 和本独立报告。基线提交 `34e8095`。
用户已报告 Android 正常显示视频、约 40 fps 足够；不再为 45 fps 优先优化。
该反馈只作为基础显示验收记录，没有手机型号、10 分钟窗口、日志或故障恢复数据，G8/G7 整体不标通过。

## 必要修正

0.3 的 STOP/REKEY 已清理协议会话，但 Activity 最后一张 Bitmap 和待显示 Bitmap 未同步清除。
0.4 在 StreamClient 现有单工作线程上通知画面清理：换钥先清除旧画面，再发新 HELLO；
STOP、关闭或连接失败在当前密码/解码操作结束并清理 Session 后通知，避免清理后迟到的旧帧。
Activity 清理待显示回调与 Bitmap，再在 UI 线程释放已显示 Bitmap；旧连接回调仍由 generation 隔离。
显示 fps 改从首张实际显示图像开始计算，换钥重置显示计时，握手等待不再混入分母。
接收线程、OkHttp、Session 的关闭仍用原有实现，没有新增后台播放、录像、服务器或依赖。

## 验证与产物

- `mobile/test.ps1 -Jdk C:/Users/23976/AppData/Local/Programs/STM32CubeMX/jre`：
  `ANDROID_CORE_OK checks=160 MLKEM_KAT=25 GCM_KAT=20`，`PAIRING_CONFIG_OK checks=30`。
  新增失败连接的清理通知与重复 close 幂等检查。
- `.venv/Scripts/python.exe sim/tb/test_three_end.py`：五会话通过，包含重连、REKEY、认证 STOP、
  丢首个 HELLO_ACK 重试。NetworkCli 核对换钥视频前恰好一次清理、最终关闭恰好一次清理；
  JVM 在测试超时内自然退出，relay 模拟设备关闭。使用公开 fixture、实际 OkHttp/回环 WebSocket/
  板端 C 会话与 ML-KEM，USB/DMA 模拟；不是实板或手机结果。
- Gradle 8.9 / AGP 8.7.3 / JDK 21 离线缓存构建成功：14 秒，31 tasks，10 executed。
  使用已有 ignored `tmp/json_mobile_init.gradle` 与 `build/mobile_toolchain/gradle-user` 命中官方 CDN 缓存，
  未持久修改官方仓库；默认仓库缓存未命中那次构建失败不算成功证据。
- `apksigner verify --verbose --print-certs --min-sdk-version 26`：v2 验证通过；
  `aapt dump badging`：`org.eyepqc.mobile`，0.4 / versionCode 4，min API26 / target API35，INTERNET 与启动 Activity 正确。
- APK：`mobile/app/build/outputs/apk/debug/app-debug.apk`，4,743,182 bytes，
  SHA-256 `a217b3bb6ee9937dde6f10461347dd935919a0349b771cea6f1aaf977f81556a`。
  Android Debug 证书 SHA-256 `4d81d4c924fddebdcf83f9007586fa10a85c792fe2386592cfb566ab4ef0b81b`，
  与构建前 0.3 一致，可覆盖安装；APK 保留为 ignored 本地产物。

编译和回调测试未执行 Android Bitmap 渲染、系统文件选择器或 Activity 生命周期的手机测试。
未读取实际私钥，未操作 JTAG/USB CDC，未修改正在运行的 PC 服务、token、配对 JSON 或公共下载目录。
其余聊天并行修改的 PC/board 文件不纳入本提交。

## SD 自主启动与配对接口依赖

Android 不依赖板端身份来自 JTAG mailbox 还是 SD 启动 provider；当前代码只依赖：
ML-KEM-512 800 字节公钥、固定 pin、相同协议/派生/Finished/认证 START、PC WebSocket 记录格式。
若 SD 固件沿用同一私钥及对应公钥，PC endpoint/token 也未变化，现有 version=1 配对 JSON 可直接复用，
无需改 APK、pin、字段或业务协议。这是接口代码核对结论，尚未用实际 SD 冷启动验证。

若板端轮换身份，板端向可信 PC 提供对应公开 `public.bin` 与 SHA-256；PC 重新导出 version=1 五字段 JSON，
用户在手机导入后点击连接。若仅 PC 地址或 token 改变，同样重新导出 JSON，保留原公钥/pin。
JSON 含 token，只能可信私下传送；同文件公钥与摘要一致不是可信来源证明。
Android 不自动信任服务下发的新公钥、不静默更新 pin。板端密钥存储、熵源与 SD 安全边界由板端记录。

共享 README/goals/steps/progress 需主协调者统一更新：将基础手机显示改为用户报告约 40 fps，
取消 45 fps 优先优化，但保留 10 分钟、故障恢复及 G8/G7 待验；本轮未修改共享文件。

## 尚需手机操作的最小验证

1. 如需核对本轮修正，覆盖安装 0.4、导入同一可信 JSON，连接后确认正常认证显示。
2. 点击换钥：旧画面清空，显示“重新协商密钥”，认证后恢复；点击停止：画面清空，状态“已停止”，
   再点击连接能恢复。记录操作时间、结果和手机显示 fps。
3. 断网与恢复、切到后台再返回：旧画面和会话关闭，手动连接后恢复，不出现旧图跨会话显示。
4. 主协调者完成 SD 部署后，板卡物理冷启动、不做 JTAG 注入；等 PC 桥可接入后用原 JSON 连接，
   核对 pin/双向 Finished/视频。失败时先保留手机状态和 PC/板端诊断，不能反复重连冒充通过。
5. 在真实手机连续运行至少 10 分钟并独立记录显示 fps、丢帧、帧间停顿及错误；
   联合板端/PC 统计才能补 G8，40 fps 用户接受不替代稳定性与故障恢复证据。
