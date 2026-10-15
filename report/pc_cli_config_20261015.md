# PC CLI 1.1: command-managed configuration (2026-10-15)

## Delivered behavior

`eyepqc-1.1.exe config show`, `config set <key> <value>` and `config import <legacy.json>`
replace manual JSON maintenance. `run`/`check` use built-in public defaults and current-user settings;
they no longer implicitly load adjacent `eyepqc.json`. Explicit `--config` remains compatible with legacy JSON.

Defaults: automatic CDC, fixed local `127.0.0.1:8765`, SSH `124.70.38.245:2222`, tunnel enabled.
Material paths are relative to the EXE at runtime: `private/accounts.json`, `public/pairing.json`,
`public/server-chain.pem`, `private/server-key.pem`, `private/id_ed25519`, `public/tunnel_known_hosts`.
No real credentials, material contents or machine-specific absolute configuration paths are compiled in.

Parameters and paths persist in `%LOCALAPPDATA%/EYEPQC/pc/settings.json`, managed by the program.
LOCALAPPDATA must be an absolute local directory. Writes use a temporary file in the destination directory,
flush/fsync, then `os.replace`; failed replacement preserves the previous settings and removes the temporary file.
The bounded 16 KiB parser rejects duplicates, unknown fields, invalid types, invalid hosts/ports and UNC paths.
Damaged existing settings block show/set/import without resetting or overwriting them.

All legacy configurable fields have corresponding command keys:
`serial_port`, `accounts_file`, `pairing_file`, `tls_cert`, `tls_key`,
`tunnel.enabled`, `tunnel.host`, `tunnel.ssh_port`, `tunnel.identity_file`, `tunnel.known_hosts`.
Set resolves relative paths against the caller's working directory; import resolves them against the legacy
JSON directory. File existence/content is checked at run/check, not while setting individual paths.
Disabling the tunnel preserves its host, port and paths; importing legacy `tunnel:null` disables the tunnel
while retaining the current details. Version/Help/status/account do not load user settings.

Commands only change the next launch. They do not hot-reload or interrupt an existing viewer.
Changing the SSH host does not sign a new TLS SAN, change phone pairing/APK, or trust a new SSH host key.
TLS, known_hosts, protocol and supervisor semantics are unchanged.

## Artifact

Built with `./pc/build_exe.ps1 -Name eyepqc-1.1`, isolated Python 3.12.10 / PyInstaller 6.22.3.

- File: `build/pc_cli/dist/eyepqc-1.1.exe`
- Version: `1.1.0`
- Size: **10,274,436 bytes**
- SHA-256: `f48c8df5f7bc5bd419f5c04f41739b3f7ed8e3527fdf4cb1400756bff1609cc8`
- Old `eyepqc.exe` remains unchanged: `c3989e2bb63ea64360490c8a61f6c1f1a99ac3d85508ca74140a47f8cf772e8a`.

CArchive top-level filenames contain no `.pem`, `.json`, `.token` or `tmp/` material files.
This round builds a distinct artifact; it does not replace or restart the running old EXE.

## Verification

PC subagent executed `python -m unittest discover -s pc/tests -v`: **73/73 passed in 55.794 seconds**.
The 11 new settings tests cover built-in/no-adjacent-JSON behavior, single-key persistence, tunnel toggle retention,
set/import relative paths, strict schema/duplicates/size/types, corrupted-file preservation, atomic replace failure,
no material/service access during configuration, LOCALAPPDATA rejection, old API and explicit JSON compatibility.
Frozen EXE tests use a temporary LOCALAPPDATA and verify show/set/import/persistence, missing-material check refusal,
damaged-settings preservation, help/version independence. Frozen check also uses isolated synthetic account/TLS/public
pairing fixtures. No production account file or key contents were read by the subagent's tests or packaging.
Whitespace checks pass.

The main coordinator separately reported the following real **path-only** migration, without starting a new service:

1. Confirmed actual user settings did not exist; new EXE show reported built-in defaults.
2. Imported the existing adjacent legacy JSON; show reported user-settings and preserved COM7, existing account file,
   public pairing/certificate and SSH material paths. No account/password was changed.
3. Default check, without `--config`, returned `CONFIG_OK ... network_started=false`.
4. Old executable hash remained unchanged and the existing 8765 listener PID25372 remained active.
5. Independently reran the 11 settings tests successfully in 7.454 seconds.

These coordinator results are distinct from the subagent's isolated tests. They do not represent a 1.1 live-video trial.
The user was viewing through the old instance; no USB/JTAG, business connection, takeover, deployment, shutdown or
restart was performed by this implementation task. Shared documentation and commits are handled by the coordinator.

## Usage

```powershell
./eyepqc-1.1.exe config show
./eyepqc-1.1.exe config set serial_port auto
./eyepqc-1.1.exe config set accounts_file C:/EYEPQC/private/accounts.json
./eyepqc-1.1.exe config set tunnel.enabled false
./eyepqc-1.1.exe config set tunnel.enabled true
./eyepqc-1.1.exe check
# Run only after the existing viewer/service has stopped normally.
./eyepqc-1.1.exe run
```

User settings contain parameters/paths, not credentials. Account, TLS and SSH private files remain separate and
must retain Windows user-directory ACL protection. This change does not embed secrets or remove external materials.
