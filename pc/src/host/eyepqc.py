"""Foreground PC relay CLI. No board provisioning or embedded credentials."""

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

VERSION = '1.1.0'
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
    configure = commands.add_parser('config', help='Manage local parameters and paths without opening materials')
    edits = configure.add_subparsers(dest='config_command', required=True)
    edits.add_parser('show', help='Show effective configuration and settings location')
    set_command = edits.add_parser('set', help='Set one parameter; file paths resolve against current directory')
    set_command.add_argument('key', choices=cli_settings.KEYS)
    set_command.add_argument('value')
    importer = edits.add_parser('import', help='Import legacy JSON; file paths resolve against its directory')
    importer.add_argument('file', type=Path)
    commands.add_parser('status', help='Read Windows TCP state without reading private files')
    account = commands.add_parser('account', help='Create a new salted-scrypt file; refuses overwrite')
    account.add_argument('--file', type=Path, required=True)
    account.add_argument('--username', required=True)
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
        elif args.command == 'account':
            hint = 'account file exists, username/password invalid or destination unavailable; choose a new private file'
            if args.file.exists():
                raise ValueError('account file exists; use a new private file and restart with that file')
            password = getpass.getpass('New password: ')
            if password != getpass.getpass('Repeat password: '):
                raise ValueError('passwords differ')
            accounts.create_account(args.file, args.username, password)
            print('ACCOUNT_CREATED; use config set accounts_file <new-file>, then restart the relay to apply.')
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
