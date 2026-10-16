"""Foreground PC relay CLI; explicit optional development USB bootstrap, no embedded credentials."""

import argparse
import asyncio
import getpass
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
from types import SimpleNamespace

import accounts
import cloud_tunnel
import relay
import cli_settings

VERSION = '1.3.1'
PORT = 8765


class ServiceError(RuntimeError):
    """Static CLI diagnostics or numeric exit status, never private input."""


def load_config(path=None):
    if path is None:
        config = cli_settings.effective()
    else:
        path = Path(path).resolve()
        config = cli_settings.normalize(cli_settings.read_json(path), path.parent, legacy=True)

    def file(value):
        target = Path(value)
        if not target.is_file() or target.stat().st_size == 0:
            raise ValueError('a configured file is missing or empty')
        return target

    serial_port = config['serial_port']
    if serial_port is not None and (not isinstance(serial_port, str) or not serial_port or len(serial_port) > 128
                                    or any(ord(c) < 32 for c in serial_port)):
        raise ValueError('serial_port must be a port name or null for automatic discovery')
    args = SimpleNamespace(host='127.0.0.1', port=PORT, serial_port=serial_port, token_file=None,
                           **{key: file(config[key]) for key in ('accounts_file', 'pairing_file', 'tls_cert', 'tls_key')})
    tunnel = config['tunnel']
    ssh = None
    if tunnel['enabled']:
        ssh = cloud_tunnel.command(tunnel['host'], file(tunnel['identity_file']), file(tunnel['known_hosts']), tunnel['ssh_port'])
    return args, ssh


def check_materials(args):
    accounts.Accounts(args.accounts_file)
    relay.read_pairing(args.pairing_file)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(args.tls_cert, args.tls_key)


def ensure_port_free(port=PORT):
    with socket.socket() as probe:
        if os.name == 'nt':
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            raise ServiceError('relay port already occupied; inspect status and stop the old relay normally') from None


async def run_services(args, ssh):
    ready = asyncio.Event()
    relay_task = asyncio.create_task(relay.run(args, ready=ready))
    ready_task = asyncio.create_task(ready.wait())
    child = None
    child_task = None
    spawn_task = None
    try:
        await asyncio.wait({relay_task, ready_task}, return_when=asyncio.FIRST_COMPLETED)
        if relay_task.done():
            await relay_task
            raise ServiceError('relay exited before startup')
        if ssh is None:
            print('PC_RUNNING local relay only; Ctrl+C stops.', flush=True)
            await relay_task
        else:
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            spawn_task = asyncio.create_task(asyncio.create_subprocess_exec(*ssh, stdin=subprocess.DEVNULL, creationflags=flags))
            child = await asyncio.shield(spawn_task)
            child_task = asyncio.create_task(child.wait())
            print('PC_RUNNING relay ready, SSH connecting; Ctrl+C stops both. Video requires a ready G6 board.', flush=True)
            await asyncio.wait({relay_task, child_task}, return_when=asyncio.FIRST_COMPLETED)
            if relay_task.done():
                await relay_task
                raise ServiceError('relay exited')
            raise ServiceError(f'SSH exited with code {child_task.result()}; relay stopped, no automatic reconnect')
    finally:
        # Cancellation during process creation still leaves an owned child to reap.
        if child is None and spawn_task is not None:
            try:
                child = await asyncio.shield(spawn_task)
            except OSError:
                pass
        # Only terminate the SSH child created by this invocation; never kill an existing service.
        if child is not None and child.returncode is None:
            try:
                child.terminate()
            except ProcessLookupError:
                pass
        relay_task.cancel()
        ready_task.cancel()
        await asyncio.gather(relay_task, ready_task, return_exceptions=True)
        if child is not None:
            try:
                await asyncio.wait_for(child.wait(), 5)
            except asyncio.TimeoutError:
                child.kill()
                await child.wait()
        if child_task is not None:
            await asyncio.gather(child_task, return_exceptions=True)


def status():
    if os.name != 'nt':
        raise RuntimeError('status requires Windows PowerShell')
    command = ("$ErrorActionPreference='Stop'; Get-NetTCPConnection | "
               "Where-Object { $_.LocalPort -eq 8765 -or ($_.RemotePort -eq 2222 -and $_.State -eq 'Established') } | "
               "Select-Object State,LocalAddress,LocalPort,RemoteAddress,RemotePort,OwningProcess | ConvertTo-Json -Compress")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('TCP status check failed')
    print(result.stdout.strip() or 'No relay/tunnel TCP endpoints found.')
    print('TCP state only; not proof of authenticated video, board readiness or tunnel ownership.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version='EYEPQC PC ' + VERSION)
    commands = parser.add_subparsers(dest='command')
    for name, help_text in (('run', 'Run relay and optional SSH tunnel; Ctrl+C stops'),
                            ('check', 'Validate local files only; no USB or network connection')):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument('--config', type=Path, help='explicit legacy JSON; otherwise built-in defaults and user settings')
        if name == 'run':
            sub.add_argument('--dev-usb-bootstrap', action='store_true',
                             help='Explicit trusted local USB development initialization before listening; not production security')
            sub.add_argument('--dev-identity-file', type=Path,
                             help='Explicit ACL-protected local test ML-KEM secret key; never stored in settings or the EXE')
    configure = commands.add_parser('config', help='Manage local parameters and paths without opening materials')
    edits = configure.add_subparsers(dest='config_command', required=True)
    edits.add_parser('show', help='Show effective configuration and settings location')
    set_command = edits.add_parser('set', help='Set one parameter; file paths resolve against current directory')
    set_command.add_argument('key', choices=cli_settings.KEYS)
    set_command.add_argument('value')
    importer = edits.add_parser('import', help='Import legacy JSON; file paths resolve against its directory')
    importer.add_argument('file', type=Path)
    commands.add_parser('status', help='Read Windows TCP state without reading private files')
    install = commands.add_parser('install-data', help='Import local runtime materials into current-user data; no service action')
    install.add_argument('--config', type=Path, help='optional legacy source JSON; otherwise current user settings')
    account = commands.add_parser('account', help='List/add/passwd/delete accounts; old --file/--username creates a new file')
    account.add_argument('operation', choices=('list', 'add', 'passwd', 'delete'), nargs='?')
    account.add_argument('--file', type=Path, help='override current settings accounts_file')
    account.add_argument('--username')
    account.add_argument('--yes', action='store_true', help='explicitly confirm account deletion')
    args = parser.parse_args(argv)
    hint = 'configuration or configured file missing/invalid; run config show and check'
    try:
        if args.command is None:
            parser.print_help()
            return 0
        if args.command == 'config':
            hint = 'configuration key/value invalid, LOCALAPPDATA not local/absolute, or existing settings damaged; settings preserved'
            if args.config_command == 'show':
                cli_settings.show()
            elif args.config_command == 'set':
                cli_settings.set_value(args.key, args.value)
                print('CONFIG_SAVED; applies on next run')
            else:
                cli_settings.import_legacy(args.file)
                print('CONFIG_IMPORTED; applies on next run')
        elif args.command == 'status':
            hint = 'Windows TCP status unavailable; verify PowerShell access'
            status()
        elif args.command == 'install-data':
            import install_data
            hint = 'local material import failed or existing data differs; files/settings preserved; verify source paths and private ACL'
            install_data.install(args.config)
            print('DATA_INSTALL_OK; local files/settings only; no service started or stopped')
        elif args.command == 'account':
            hint = 'account operation refused: invalid/damaged file, user exists/missing, limit/last-user guard or concurrent writer; no changes applied'
            operation = args.operation
            if operation is None and (args.file is None or args.username is None):
                raise ServiceError('legacy account creation requires --file and --username')
            if operation == 'list' and (args.username is not None or args.yes):
                raise ServiceError('account list accepts only optional --file')
            if operation != 'list' and args.username is None:
                raise ServiceError('account operation requires --username')
            if args.yes and operation != 'delete':
                raise ServiceError('--yes is only valid for account delete')
            if operation == 'delete' and not args.yes:
                raise ServiceError('account delete requires --yes; the final user cannot be deleted')
            path = args.file if args.file is not None else Path(cli_settings.effective()['accounts_file'])
            if operation == 'list':
                users = accounts.read_users(path)
                for name in sorted(users):
                    print(name)
                print('ACCOUNT_COUNT=' + str(len(users)))
            elif operation == 'delete':
                accounts.change_account(path, 'delete', args.username, confirmed=True)
                print('ACCOUNT_UPDATED; restart the relay normally to apply; active service keeps its startup snapshot')
            else:
                if operation is None and path.exists():
                    raise ServiceError('account file exists; use account add/passwd or choose a new private file')
                password = getpass.getpass('New password: ')
                if password != getpass.getpass('Repeat password: '):
                    raise ServiceError('passwords differ; account not changed')
                if operation is None:
                    accounts.create_account(path, args.username, password)
                    print('ACCOUNT_CREATED; use config set accounts_file <new-file>, then restart the relay to apply.')
                else:
                    accounts.change_account(path, operation, args.username, password)
                    print('ACCOUNT_UPDATED; restart the relay normally to apply; active service keeps its startup snapshot')
        else:
            if args.command == 'run':
                hint = 'relay port unavailable; run status and stop the old service normally'
                ensure_port_free()
            hint = 'configuration schema or configured file missing/invalid; run config show and check'
            settings, ssh = load_config(args.config)
            hint = 'account/pairing format or TLS certificate/key invalid; verify configured local files'
            check_materials(settings)
            if args.command == 'check':
                print('CONFIG_OK offline_only=true board_validated=false network_started=false')
            else:
                if args.dev_usb_bootstrap != (args.dev_identity_file is not None):
                    raise ServiceError('--dev-usb-bootstrap and --dev-identity-file must be supplied together')
                if args.dev_usb_bootstrap:
                    if not settings.serial_port or settings.serial_port.lower() == 'auto':
                        raise ServiceError('development bootstrap requires a configured explicit COM port; use config set serial_port COMx')
                    import dev_usb_bootstrap
                    hint = 'development USB bootstrap failed; verify trusted local board/profile, explicit COM, private ACL and public pairing; no listener started'
                    settings.dev_bootstrap_factory = lambda: dev_usb_bootstrap.open_bootstrapped(
                        settings.serial_port, args.dev_identity_file, settings.pairing_file)
                    device = settings.dev_bootstrap_factory()
                    dev_usb_bootstrap.close_device(device)
                    print('DEV_USB_READY development_only=true identity_in_sd=false', flush=True)
                hint = 'relay/TLS/SSH startup failed; check configured files, OpenSSH and service logs'
                asyncio.run(run_services(settings, ssh))
        return 0
    except KeyboardInterrupt:
        print('PC_STOPPED')
        return 130
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        # Do not print exception strings: malformed account files can echo private contents.
        print('PC_ERROR: ' + (str(exc) if isinstance(exc, ServiceError) else hint), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
