# CF7020B PS USB0 从机可行性验证（2026-09-29）

目的：判断 USB Slave 能否替代计划中的 PS 以太网传输。只验证独立传输链路，
不包含摄像头、AES-GCM、ML-KEM 或主机显示。

- 板卡：领航者 CF7020B，P4 跳帽置 USB Slave，USB Slave Type-C 接主机；JTAG 与 CH340 COM4 仍连接。
- Vivado 2026.1 启用 PS USB0：MIO28～39、PHY 复位 MIO9；XSA 和 bitstream 构建成功，验证后已纳入默认 PS 配置。
- Vitis Standalone 使用 AMD `usbps` 驱动，临时 CDC ACM 固件经 JTAG 下载，只改易失性状态，不写 SD/QSPI。
- Windows 识别 `VID_03FD&PID_7020` 为 USB 串行设备，本次端口 COM7；该 VID/PID 仅用于临时实验，不能作为正式产品标识。
- 主机按 DTR 启停，接收 16 KiB 数据块，检查 `EYEP` 标记、连续块序号及全部有效载荷字节。
- 30.047 秒：30016 个连续完整块，首序号 0、末序号 30015；491,782,144 字节完整块逐字节正确，主机总接收约 16.367 MB/s。

复现（在仓库根目录 PowerShell；两个 `usb_probe_repro_1` 目录须事先不存在）：

```powershell
$env:EYEPQC_USB_PROBE_XSA=(Resolve-Path 'build/vivado/usb_probe_repro_1/m01.xsa').Path
& 'D:/AmdDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source board/prj/build_m01.tcl -tclargs build/vivado/usb_probe_repro_1
$env:EYEPQC_USB_PROBE_VITIS=(Resolve-Path 'build/vitis/usb_probe_repro_1').Path
& 'D:/AmdDesignTools/2026.1/Vitis/bin/vitis.bat' -s board/prj/build_usb_probe.py
& 'D:/AmdDesignTools/2026.1/Vivado/bin/xsdb.bat' board/prj/run_usb_probe_jtag.tcl $env:EYEPQC_USB_PROBE_VITIS
python board/prj/test_usb_probe.py --seconds 30
```

第一次逐块读取并同步校验的主机探针在接近满速时偶发块错位；改为大块连续接收、
停流后逐字节校验后，5 秒与 30 秒测试均通过。这提示正式 M12 要持续抽空 USB 接收
缓冲，避免 Python 显示/解密阻塞读线程。上述 16.37 MB/s 是合成数据极限链路结果，
不能据此宣称加密视频已经达到 45 fps；G4～G7 仍需完整端到端实测。

## M11 固定内容中间门禁

在同一 CDC 固件中增加主机发起的 `R`（固定记录）和 `J`（上传 JPEG 后回传）模式，
保留 `T` 极限吞吐模式。`R` 模式发送 `doc/protocol.md` 的通道 2 + 40 字节视频包头
和 1400 字节明文载荷；30.531 秒接收并校验 30519 条连续记录，约 1.442 MB/s。
`J` 模式只接收 4～65536 字节且具有 JPEG SOI/EOI 的输入，再按同一协议分包。
实拍 640×480 的 13982 字节文件经 USB 往返，10 包重组后逐字节相同并可解码；
320×240 的 4181 字节文件 3 包同样通过。USB 设备标识仍仅供临时实验。

```powershell
python board/prj/test_usb_records.py --seconds 30
python board/prj/test_usb_jpeg.py data/captures/g3_20260928_191037_572878/frame_000
```

这完成了 M11 的固定数据与固定 JPEG 两项中间测试；`J` 的 JPEG 来自主机上传，
并非此时板卡摄像头直接采集，因此不将其标作 G4。
