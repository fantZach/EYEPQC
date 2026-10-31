"""Mock SSH execution; only the optional ssh -G test invokes the real client offline."""

import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/host'))
from cloud_tunnel import command, main


class TunnelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='eyepqc tunnel ')
        self.addCleanup(self.tmp.cleanup)
        self.key = Path(self.tmp.name)/'fixture identity'
        self.known = Path(self.tmp.name)/'fixture known hosts'
        self.key.write_text('private fixture must never be printed')
        self.known.write_text('public fixture not a verified host key')
        self.argv = ['--cloud-host', 'cloud.example', '--identity-file', str(self.key),
                     '--known-hosts', str(self.known)]

    def invoke(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(args)
        self.assertNotIn(self.key.read_text(), output.getvalue())
        return result, output.getvalue()

    @patch('cloud_tunnel.shutil.which', return_value='fixture-ssh')
    def test_default_plan_never_executes_or_reads_keys(self, _):
        with patch('cloud_tunnel.subprocess.run') as run, \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('private read')), \
                patch.object(Path, 'read_text', side_effect=AssertionError('private read')):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(self.argv), 0)
            run.assert_not_called()
        self.assertNotIn(self.key.read_text(), output.getvalue())
        self.assertIn('"network_started": false', output.getvalue())

    @patch('cloud_tunnel.shutil.which', return_value='fixture-ssh')
    def test_arguments_and_failures(self, _):
        with patch('cloud_tunnel.subprocess.run', return_value=subprocess.CompletedProcess([], 255)) as run:
            status, printed = self.invoke([*self.argv, '--mode', 'Run'])
        self.assertEqual(status, 255)
        self.assertIn('SSH_TUNNEL_FAILED', printed)
        args = run.call_args.args[0]
        self.assertEqual(args[-3:], ['-R', '0.0.0.0:8765:127.0.0.1:8765', 'eyepqc-tunnel@cloud.example'])
        self.assertEqual(args[args.index('-i')+1], self.key.resolve().as_posix())
        self.assertIn('-N', args)
        self.assertIn('-T', args)
        self.assertEqual(args[args.index('-p')+1], '22022')
        for option in ('StrictHostKeyChecking=yes','BatchMode=yes','IdentitiesOnly=yes',
                       'ExitOnForwardFailure=yes','ConnectTimeout=10',
                       'ServerAliveInterval=15','ServerAliveCountMax=3','IdentityAgent=none'):
            self.assertIn(option, args)
        self.assertNotIn('shell', run.call_args.kwargs)
        run.assert_called_once()
        for failure in (OSError('fixture error'), subprocess.TimeoutExpired('ssh', 15)):
            with patch('cloud_tunnel.subprocess.run', side_effect=failure) as run:
                self.assertEqual(self.invoke([*self.argv, '--mode', 'Check'])[0], 1)
                run.assert_called_once()

    @patch('cloud_tunnel.shutil.which', return_value='fixture-ssh')
    def test_check_only_uses_G_and_propagates_config_error(self, _):
        with patch('cloud_tunnel.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'host cloud.example\n')) as run:
            status, output = self.invoke([*self.argv, '--mode', 'Check'])
        self.assertEqual(status, 0)
        self.assertEqual(run.call_args.args[0][1], '-G')
        self.assertEqual(run.call_args.kwargs['timeout'], 15)
        self.assertIn('offline_only=true', output)
        with patch('cloud_tunnel.subprocess.run', return_value=subprocess.CompletedProcess([], 7)):
            self.assertEqual(self.invoke([*self.argv, '--mode', 'Check'])[0], 7)

    def test_validation_does_not_launch(self):
        with patch('cloud_tunnel.subprocess.run') as run:
            for host in ('-oProxyCommand=bad', 'https://cloud.example', 'user@cloud.example',
                         'cloud:22022', 'cloud\nexample', '999.2.3.4', '', 'a'*64+'.example'):
                with self.assertRaises(ValueError):
                    command(host, self.key, self.known)
            for port in (0, 65536, '22022'):
                with self.assertRaises(ValueError):
                    command('cloud.example', self.key, self.known, port)
            with self.assertRaises(ValueError):
                command('cloud.example', self.key.parent/'missing', self.known)
            for invalid in ('//remote/share/key', 'bad"path', 'bad\npath', '%h-key', '${HOME}/key'):
                with self.assertRaises(ValueError):
                    command('cloud.example', invalid, self.known)
            self.known.write_text('')
            with self.assertRaises(ValueError):
                command('cloud.example', self.key, self.known)
            run.assert_not_called()

    @unittest.skipUnless(shutil.which('ssh'), 'OpenSSH unavailable')
    def test_real_ssh_G_offline_config_and_spaces(self):
        status, output = self.invoke([*self.argv, '--mode', 'Check'])
        self.assertEqual(status, 0, output)
        parsed = output.lower().replace('[', '').replace(']', '')
        for setting in ('user eyepqc-tunnel', 'port 22022', 'batchmode yes',
                        'stricthostkeychecking true', 'exitonforwardfailure yes',
                        'serveraliveinterval 15', 'serveralivecountmax 3',
                        'remoteforward 0.0.0.0:8765 127.0.0.1:8765'):
            self.assertIn(setting, parsed)
        self.assertIn(self.known.resolve().as_posix().lower(), parsed)


if __name__ == '__main__':
    unittest.main()
