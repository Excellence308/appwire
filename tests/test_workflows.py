import contextlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

from appwire import client, local, cli
from appwire.daemon import dispatch
from appwire.backend import Backend, command, OperationError
from test_core import CONFIG


class Workflows(unittest.TestCase):
    def setUp(self):
        previous_cwd = os.getcwd()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(os.chdir, previous_cwd)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, XDG_STATE_HOME=str(self.root / 'user'), XDG_DATA_HOME=str(self.root / 'data'))
        self.env.start()
        self.addCleanup(self.env.stop)
        (self.root / 'runtime').mkdir()
        (self.root / 'netns').mkdir()
        self.backend = Backend(1000, self.root / 'profiles', self.root / 'runtime', self.root / 'netns')
        self.backend.import_config('test', CONFIG)

    def test_operation_error_never_exposes_tool_output(self):
        response = Mock(returncode=1, stdout='private-secret', stderr='private-secret')
        with patch('appwire.backend.subprocess.run', return_value=response):
            with self.assertRaises(OperationError) as raised:
                command('/usr/bin/wg', 'setconf', 'fixture', '/dev/stdin', input='private-secret')
        self.assertEqual(raised.exception.code, 'configure_wireguard')
        self.assertNotIn('private-secret', str(raised.exception))

    def test_import_requires_explicit_replacement(self):
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.backend.import_config('test', CONFIG)
        self.backend.import_config('test', CONFIG, replace=True)
        self.assertEqual(self.backend.path('test').read_text(), CONFIG)

    def test_replacement_rpc_rejects_truthy_non_boolean(self):
        with self.assertRaisesRegex(ValueError, 'boolean'):
            dispatch(self.backend, {'op': 'import', 'profile': 'test', 'config': CONFIG, 'replace': 'false'}, [])

    def test_rename_preserves_credentials_and_does_not_overwrite(self):
        self.backend.rename('test', 'new')
        self.assertFalse(self.backend.path('test').exists())
        self.assertEqual(self.backend.path('new').read_text(), CONFIG)
        self.backend.import_config('test', CONFIG)
        with self.assertRaises(ValueError):
            self.backend.rename('new', 'test')

    def test_rename_active_profile_refused(self):
        (self.backend.netns / self.backend.namespace('test')).touch()
        with self.assertRaisesRegex(ValueError, 'Stop'):
            self.backend.rename('test', 'new')

    def test_bad_profile_does_not_hide_good_profiles(self):
        self.backend.import_config('other', CONFIG)
        actual = self.backend.status
        def status(name):
            if name == 'test':
                raise RuntimeError('a private failure detail')
            return actual(name)
        with patch.object(self.backend, 'status', side_effect=status):
            result = self.backend.profiles()
        self.assertEqual({p['profile']: p['state'] for p in result}, {'other': 'stopped', 'test': 'error'})
        self.assertNotIn('private failure', json.dumps(result))

    def test_stopped_launch_never_calls_spawn(self):
        with patch('appwire.daemon.spawn') as spawn, self.assertRaisesRegex(RuntimeError, 'stopped'):
            dispatch(self.backend, {'op': 'run', 'profile': 'test', 'argv': ['true'], 'env': {}}, [])
        spawn.assert_not_called()

    def test_missing_service_and_permissions_close_client_socket(self):
        for error, text in [(FileNotFoundError(), 'unavailable'), (ConnectionRefusedError(), 'unavailable'), (PermissionError(), 'log out')]:
            sock = Mock()
            sock.connect.side_effect = error
            with patch('appwire.client.socket.socket', return_value=sock), self.assertRaisesRegex(RuntimeError, text):
                client.connect()
            sock.close.assert_called_once()

    def test_names_from_proton_exports(self):
        self.assertEqual(local.suggested_name('proton-us-ca-245-US-CA-245.conf'), 'proton-us-ca-245')
        self.assertEqual(local.suggested_name('A weird server!.conf'), 'a-weird-server')


    def test_setup_enables_without_restarting_service(self):
        with patch('appwire.local.os.geteuid', return_value=1000), patch('appwire.local.subprocess.run') as run:
            local.setup()
        calls = [c.args[0] for c in run.call_args_list]
        self.assertIn(['/usr/bin/sudo', '/usr/bin/systemctl', 'enable', '--now', 'appwire.service'], calls)
        self.assertFalse(any('restart' in c for c in calls))


    def test_removed_cli_features_are_not_available(self):
        for command in ('sessions', 'apps', 'history', 'save-app', 'launch', 'launch-id', 'desktop-shortcut', 'measure', 'launch-logged'):
            with self.subTest(command=command), patch.object(cli.sys, 'argv', ['appwire', command]), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.main()

    def test_run_requires_existing_tunnel_and_has_no_host_launch(self):
        with patch.object(cli.sys, 'argv', ['appwire', 'run', 'test', '--', 'example-app']), patch('appwire.client.run', side_effect=RuntimeError('stopped')) as run, patch('appwire.client.call') as call, patch('appwire.cli.subprocess.call') as direct, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(), 1)
        run.assert_called_once_with('test', ['example-app'])
        call.assert_not_called()
        direct.assert_not_called()

    def test_continuous_logging_stays_bounded(self):
        local.append_log(b'x' * (5 * 1024 * 1024) + b'latest')
        for name in ('applications.log', 'applications.previous.log'):
            self.assertLessEqual((local.directory() / name).stat().st_size, 2 * 1024 * 1024)
        self.assertTrue((local.directory() / 'applications.log').read_bytes().endswith(b'latest'))


if __name__ == '__main__':
    unittest.main()
