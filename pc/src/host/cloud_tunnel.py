"""Foreground OpenSSH reverse TCP tunnel. Plan is the default; Check is offline."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def command(host, identity_file, known_hosts, ssh_port=22022):
    if not isinstance(ssh_port, int) or not 1 <= ssh_port <= 65535:
        raise ValueError('SSH port must be 1..65535')
    if (not isinstance(host, str) or len(host) > 253
            or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part)
                       for part in host.split('.'))):
        raise ValueError('cloud host must be an IPv4 address or DNS name without URL/user/port')
    if all(part.isdigit() for part in host.split('.')):
        ipaddress.IPv4Address(host)
    paths = []
    for value in (identity_file, known_hosts):
        if (str(value).startswith(('\\\\', '//'))
                or any(c in str(value) for c in ('"', '\n', '\r', '\x00', '%', '$'))):
            raise ValueError('SSH files must use literal local paths without quotes or expansion tokens')
        path = Path(value).resolve()
        if any(c in str(path) for c in ('"', '\n', '\r', '\x00', '%', '$')):
            raise ValueError('invalid SSH file path')
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError('dedicated identity and verified known_hosts files must exist and be nonempty')
        paths.append(path.as_posix())
    ssh = shutil.which('ssh')
    if not ssh:
        raise RuntimeError('OpenSSH client not installed or not on PATH')
    options = dict(StrictHostKeyChecking='yes', BatchMode='yes', IdentitiesOnly='yes',
                   ExitOnForwardFailure='yes', ConnectTimeout='10', ServerAliveInterval='15',
                   ServerAliveCountMax='3', UserKnownHostsFile=f'"{paths[1]}"',
                   GlobalKnownHostsFile=os.devnull, UpdateHostKeys='no',
                   PreferredAuthentications='publickey', PasswordAuthentication='no',
                   KbdInteractiveAuthentication='no', IdentityAgent='none',
                   ForwardAgent='no', ForwardX11='no', ControlMaster='no', ControlPath='none')
    args = [ssh, '-F', os.devnull, '-N', '-T', '-p', str(ssh_port), '-i', paths[0]]
    for name, value in options.items():
        args.extend(['-o', f'{name}={value}'])
    args.extend(['-R', '0.0.0.0:8765:127.0.0.1:8765', f'eyepqc-tunnel@{host}'])
    return args


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('Plan', 'Check', 'Run'), default='Plan')
    parser.add_argument('--cloud-host', required=True)
    parser.add_argument('--identity-file', type=Path, required=True)
    parser.add_argument('--known-hosts', type=Path, required=True)
    parser.add_argument('--ssh-port', type=int, default=22022)
    args = parser.parse_args(argv)
    try:
        ssh_args = command(args.cloud_host, args.identity_file, args.known_hosts, args.ssh_port)
        if args.mode == 'Plan':
            print(json.dumps(dict(mode='Plan', network_started=False, argv=ssh_args), indent=2))
            return 0
        if args.mode == 'Check':
            result = subprocess.run([ssh_args[0], '-G', *ssh_args[1:]],
                                    capture_output=True, text=True, timeout=15)
            if result.returncode:
                print('OpenSSH offline configuration check failed')
                return result.returncode
            print(result.stdout, end='')
            print('SSH_CONFIG_CHECK_OK offline_only=true host_key_not_yet_verified=true')
            return 0
        print('SSH_TUNNEL_FOREGROUND: Ctrl+C stops; failures exit without reconnecting.', flush=True)
        result = subprocess.run(ssh_args)
        if result.returncode:
            print(f'SSH_TUNNEL_FAILED exit_code={result.returncode}', flush=True)
        return result.returncode
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f'SSH_TUNNEL_ERROR {type(exc).__name__}: {exc}')
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
