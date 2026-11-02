# PC binary third-party notices

The project release `v1.0.0` contains the independently versioned Windows PC component **1.3.2**.
The **1.4.0** release uses the same packaged runtime dependencies and retains these notices.
Developer certificate preparation installs its own Python dependencies separately; those packages are not embedded in the CLI.
The notices below cover its Python runtime, runtime dependencies, executable packager, and installer.
Keep this document and the complete [`licenses/`](licenses/) directory with redistributed binaries.
EYEPQC's original code is covered by the root [MIT License](../LICENSE). Upstream components retain their respective licenses.

| Component | Version | License / full text | Upstream |
| --- | --- | --- | --- |
| CPython and bundled runtime libraries | 3.12.10 | [Python license and bundled library notices](licenses/python-3.12.10.txt) | [python.org](https://www.python.org/) |
| Expat (via CPython) | 2.7.1 | [MIT](licenses/expat-2.7.1.txt) | [libexpat](https://github.com/libexpat/libexpat/tree/R_2_7_1) |
| OpenSSL (via CPython) | 3.0.16 | [Apache-2.0](licenses/openssl-3.0.16.txt) | [OpenSSL](https://github.com/openssl/openssl/tree/openssl-3.0.16) |
| zlib (via CPython) | 1.3.1 | [zlib license](licenses/zlib-1.3.1.txt) | [zlib](https://github.com/madler/zlib/tree/v1.3.1) |
| pySerial | 3.5 | [BSD-3-Clause](licenses/pyserial-3.5.txt) | [pyserial](https://github.com/pyserial/pyserial/tree/v3.5) |
| websockets | 15.0.1 | [BSD-3-Clause](licenses/websockets-15.0.1.txt) | [websockets](https://github.com/python-websockets/websockets/tree/15.0.1) |
| PyInstaller bootloader / runtime hooks | 6.22.3 | [GPL-2.0-or-later with bootloader exception; Apache-2.0 runtime hooks](licenses/pyinstaller-6.22.3.txt) | [PyInstaller](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3) |
| Inno Setup installer | 6.7.3 | [Inno Setup license](licenses/inno-setup-6.7.3.txt) | [jrsoftware.org](https://jrsoftware.org/) |

The PyInstaller bootloader exception permits distributing the combined application without imposing
the bootloader's GPL terms on the application's own code. Runtime hook notices remain applicable.
CPython's complete license file includes its bundled third-party notices; retain the whole file.
No optional serial HID backend or ML-KEM Python package is present in the PC CLI archive.

The Windows installer is built offline using the existing publisher-signature/hash-verified compiler.
It is not a code-signed EYEPQC application and has not received independent antivirus certification.
Build-time tools not bundled in the output are not part of this runtime inventory.
