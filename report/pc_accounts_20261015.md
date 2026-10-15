# PC account maintenance CLI 1.2.1 (2026-10-15)

## Scope

Added `account list`, `account add --username NAME`, `account passwd --username NAME`,
and `account delete --username NAME --yes`. All accept optional `--file`; otherwise they use the
current user settings `accounts_file`, normally `%LOCALAPPDATA%/EYEPQC/pc/data/private/accounts.json`
after installation. The original `account --file FILE --username NAME` and `create_account` API remain
create-only and do not require readable user settings.

Add refuses duplicate users; passwd requires an existing user; delete requires explicit confirmation and
refuses deletion of the last user. At most 100 users are accepted. New passwords are entered twice with
getpass, never as command-line arguments. Usernames/passwords follow Android ISO-control rejection
(0..31, 127..159), retaining normal Unicode and password whitespace within 128/1024 UTF-8 byte limits.
List displays only usernames/count, never salt/hash/password. No original password recovery is provided.

The JSON schema remains `{username: {salt, hash}}`, with fresh random 16-byte salt, fixed scrypt
N=131072/r=8/p=1/maxmem=256MiB and 32-byte result. This is password-hash storage, not an encrypted database.
Account input is bounded to 64KiB and strictly rejects duplicate fields, malformed/unknown fields, bad
types/hex, invalid usernames and more than 100 users. Damaged databases are never silently repaired.

Writers acquire a nonblocking standard-library sidecar lock (Windows msvcrt / POSIX flock), reject
concurrent writers and preserve the lock inode after release. Writes use a same-directory temporary file,
flush/fsync and atomic publication. Existing databases use replace; create-only publication uses Windows
no-replace rename or POSIX no-replace link, protecting even against a non-cooperating creator racing the
exists check. Failed publication removes only the owned temporary file and preserves the old database.

CLI version is 1.2.1. `install-data [--config SOURCE]` delegates to the installation agent's local
`install_data.install` API and prints a static status without dumping returned summaries/materials.
Protocol, TLS and foreground service supervision remain unchanged.

## Validation and operational limits

Current account-focused fixture run: **11/11 passed in 8.031 seconds**. Coverage includes CRUD,
service snapshot retention, salt rotation, default/explicit lookup, legacy API/overwrite refusal,
confirmation and last-user guards, duplicate/corrupt/type/hex/oversize/max-user rejection, private output
redaction, atomic replace failure, the non-cooperating creator race, and a genuine second-process lock conflict.
The install-data CLI delegation test uses a fake installer and verifies no private summary is printed.
Existing 12 CLI tests also passed before the installer integration was frozen.

The single integrated regression discovered 99 tests in 61.042 seconds: 96 passed, 2 opt-in installer
tests skipped, and 1 existing settings-test fixture construction errored. That fixture called
`defaults()` after intentionally making LOCALAPPDATA invalid, before the code under test ran.
It now constructs the legacy input before overriding the environment. Frozen settings coverage also
now prefers the new 1.2.1 EXE. The corrected settings file passed **11/11 in 7.341 seconds**;
the entire suite was not rerun. The two opt-in real fixture installer tests separately passed
**2/2 in 51.927 seconds**, including the PATH matrix. These are offline/isolated results, not phone or board acceptance.

Frozen `eyepqc-1.2.1.exe --version`, `--help` and `account --help` exited 0 and exposed all four
account operations. CRUD/password hashing/confirmation/lock/failure paths were verified using the
isolated command tests above, with mocked password prompts, not by modifying the installed real database.
The frozen executable's existing isolated material `check` regression passed as part of the suite.

All account mutations were restricted to temporary fixture directories. No real accounts, login files,
running service, SSH, USB or JTAG were modified or contacted. This subagent did not stage or commit files.
Installer package/lifecycle checks are owned by the installation subagent and reported separately.

Account edits affect the disk database only. Running services retain their startup account snapshot;
normal service restart is required to apply changes and is never triggered by account commands.
No login.txt password memorandum is saved, copied or updated; external old credentials are not synchronized.
Installed private-directory ACLs protect replaced files through inheritance; explicit --file users are
responsible for selecting an appropriate private destination. The CLI cannot retrieve an original password.
