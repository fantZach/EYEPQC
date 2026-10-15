# 登录后自动配对：Android0.7 / PC

2026-10-15，用户要求账号密码正确后自动接收并导入pairing.json，取消手机手动传文件的日常步骤。
按Ponytail复用原TLS端口、Basic/scrypt、schema2解析及suite2，不新增云端账号后台或业务协议。

## 实现与信任

- 手机预填当前公网WSS地址，可修改；点击“登录并连接”先向同一服务HTTPS `/pairing.json` 认证下载，
  成功校验/保存公开配置后自动连接原 `/stream`，再执行原ML-KEM/双向Finished/START。
- PC显式 `--pairing-file` / PowerShell `-PairingFile` 指定唯一公开schema2文件；启动时冻结，最多8KiB。
  未配置则404；禁v1/额外字段/凭据/错误摘要/错误WSS地址。只读此文件，不提供目录服务或读取板端私钥。
- 配置GET共用账号验证、单哈希并发与速率限制，响应application/json、no-store、nosniff。
  不打开USB、不改变owner、不触发接管；USB不可用不妨碍获取公开配置，观看仍保留原409显式接管规则。
- 手机不跟随重定向、不放宽TLS/主机名校验，拒绝异endpoint/v1/错误摘要/超长内容。
  首次信任来自已确认的服务地址及有效TLS，公钥和摘要同时下载只证明一致性；此分发信任PC/TLS服务。
- 各地址的公开配置/指纹保存在应用私有设置，无密码/token/私钥；同地址指纹变化拒绝静默替换。
  可信手动导入保留作备用/明确换身份，错误文件不会清除原可信身份。v1仅手动导入，且不持久保存其token。
- 离开前台、关闭或下载期间停止均取消请求；generation屏障阻止迟到回调恢复旧连接/图像。

## 验证

- PC全套46项先通过；随后新增launcher账号模式拒绝检查，launcher3项、账号/配置12项再次通过。
  合计覆盖47个PC测试，未把同一项重复执行累计为新测试。
- `mobile/test.ps1`：核心160、JSON57、临时KEM37检查通过，suite2/帧处理未改。
- `mobile/test/test_auto_pairing.py`：真实OkHttp/HTTPS隔离夹具10场景通过：正常获取、错误登录拒绝、
  重定向拒绝、跨地址拒绝、v1降级拒绝、旧指纹变化拒绝、已声明/未声明长度的8KiB超限拒绝、不可信CA和错误主机名拒绝。
  公开合成凭据和临时测试CA，不触及真实USB或云端。
- Gradle8.9/AGP8.7.3/JDK21完整debug/release构建通过，22秒/73tasks（26执行），包含release vital lint。
  首次离线未匹配Google仓库缓存，复用既有官方CDN init后通过；中间一次init相对路径失败，改绝对路径。
  没有改仓库源、全局代理、关闭lint或放宽TLS。SDK提示未安装platform-tools，不影响APK生成，也未安装手机。
- API26 APK v2验签通过，Debug签名仍为
  `4d81d4c924fddebdcf83f9007586fa10a85c792fe2386592cfb566ab4ef0b81b`，可覆盖旧版。
  aapt确认versionCode7/versionName0.7、min26/target35及原包名。
- debug/release CA资源隔离复核通过：debug仍仅加入原公开测试CA；release无测试CA/NSC/debuggable。

## 公网部署与交付

检查原PC服务PID/命令行、仅有监听无观看连接后，通过其原会话Ctrl-C停止旧relay；旧日志保留。
只重启这一份PC relay，增加本轮公开PairingFile。原账号、TLS材料、SSH隧道及云端sshd未改变，未重刷板卡。
新服务日志 `tmp/cloud_wss_20261015_1/auto_pairing_relay_1.log`；隧道仍复用专用key及严格host key检查。

JVM PairingFetchCli经真实云端 `wss://124.70.38.245:8765/stream` 对应HTTPS入口，
使用本机受限login.txt成功自动获取并验证原板卡pin；错误的公开夹具账号负测拒绝。
两次退出码0，证据 `auto_pairing_public_probe_1.log` / `auto_pairing_public_reject_1.log` 位于上述ignored目录。
relay日志无SESSION_OPEN，配置请求没有打开USB。没有向云端上传pairing文件/账号/私钥或开新端口。

可安装交付文件：`tmp/cloud_wss_20261015_1/public/EYEPQC-0.7-debug.apk`，4,753,657字节，SHA256
`fd5f7188a0effae36bb3e5a8005b420de414c5fd4bae5ebc649029a7392e9006`。
与原构建APK读回哈希一致；公共目录只新增这个APK，没有复制私有凭据。
覆盖安装后保留预填公网地址，输入原本轮viewer账号密码即可，无需再导入JSON或重新生成密码。

## 尚未验收

这是软件/JVM公网下载验证，不是Android Activity、设置持久化/取消的真机验收。
此前手机视频出现QueueFull，重连握手超时，板端DDR计数观察到fatal=2/transport=1/control=1；
这不是本功能修复项，不能因获取JSON成功就宣称视频/G8/G9通过。未重启/重新provision板卡来掩盖故障。
测试CA仅用于debug，开发态JTAG身份/seed仍不是生产安全；当前SD仍为G0自检。
