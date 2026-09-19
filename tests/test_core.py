import array
import json
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from appwire.config import parse, profile_name
from appwire.client import add_applications
from appwire.backend import Backend
from appwire.daemon import dispatch, authorized
from appwire.launch import validate_launch
from appwire.protocol import send, receive, LIMIT

KEY = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='
PUBLIC = 'AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE='
CONFIG = f'''[Interface]
PrivateKey = {KEY}
Address = 10.20.0.2/32, fd00::2/128
DNS = 10.20.0.1
[Peer]
PublicKey = {PUBLIC}
Endpoint = 192.0.2.1:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
'''


class ConfigTests(unittest.TestCase):
    def test_provider_config(self):
        config = parse(CONFIG)
        self.assertEqual(config.addresses, ['10.20.0.2/32', 'fd00::2/128'])
        self.assertNotIn('Address', config.native())
        self.assertEqual(config.routes, ['0.0.0.0/0', '::/0'])
        self.assertIn('nameserver 10.20.0.1', config.resolver())

    def test_unsupported_executable_and_host_settings(self):
        for field in ('PostUp', 'PreUp', 'PreDown', 'PostDown', 'Table', 'SaveConfig', 'FwMark'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse(CONFIG.replace('[Peer]', field + ' = echo bad\n[Peer]'))

    def test_reject_malformed(self):
        cases = [CONFIG.replace(KEY, 'not-a-key'), CONFIG + '[Interface]\n', CONFIG.replace('MTU', 'bad'), CONFIG.replace('192.0.2.1:51820', 'host;touch /tmp/x:22'), CONFIG.replace('192.0.2.1:51820', 'example.org:65536'), CONFIG.replace('DNS = 10.20.0.1', 'DNS = 127.0.0.53'), CONFIG.replace('DNS = 10.20.0.1', 'DNS = ::1'), CONFIG.replace('DNS = 10.20.0.1', 'DNS = 169.254.1.1'), CONFIG.replace('0.0.0.0/0, ::/0', '192.168.1.0/24'), CONFIG.replace('Address =', 'MTU = 100\nAddress ='), CONFIG.replace('[Peer]', 'DNS = 1.1.1.1\n[Peer]'), CONFIG + '\x00', 'x' * 32769]
        # One intentionally unchanged input isn't malformed.
        cases.pop(2)
        for text in cases:
            with self.subTest(text=text[-80:]), self.assertRaises(ValueError):
                parse(text)

    def test_names_block_path_traversal(self):
        for name in ('../root', 'x/y', '-bad', 'X', '', 'a' * 33, 'x\n', 4):
            with self.subTest(name=name), self.assertRaises(ValueError):
                profile_name(name)

    def test_search_domain_and_ipv6_endpoint(self):
        config = parse(CONFIG.replace('DNS = 10.20.0.1', 'DNS = 10.20.0.1, example.org').replace('192.0.2.1:51820', '[2001:db8::1]:51820'))
        self.assertIn('search example.org', config.resolver())


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)

    def tearDown(self):
        self.a.close()
        self.b.close()

    def test_roundtrip_and_cloexec(self):
        with open('/dev/null') as source:
            send(self.a, {'op': 'run'}, [source.fileno()])
            result, fds = receive(self.b)
            self.assertEqual(result, {'op': 'run'})
            self.assertFalse(os.get_inheritable(fds[0]))
            os.close(fds[0])

    def test_malformed_json_closes_descriptors(self):
        with open('/dev/null') as source:
            before = len(os.listdir('/proc/self/fd'))
            self.a.sendmsg([b'not json'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [source.fileno()]))])
            with self.assertRaises(ValueError):
                receive(self.b)
            self.assertEqual(before, len(os.listdir('/proc/self/fd')))

    def test_oversized_send(self):
        with self.assertRaises(ValueError):
            send(self.a, {'x': 'x' * LIMIT})

    def test_truncated_rights_close_fds(self):
        with open('/dev/null') as source:
            before = len(os.listdir('/proc/self/fd'))
            self.a.sendmsg([b'{}'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [source.fileno()] * 20))])
            with self.assertRaises(ValueError):
                receive(self.b)
            self.assertEqual(before, len(os.listdir('/proc/self/fd')))


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'run').mkdir()
        (self.root / 'netns').mkdir()
        self.backend = Backend(1000, self.root / 'state', self.root / 'run', self.root / 'netns')
        self.backend.import_config('test', CONFIG)

    def test_user_ownership_and_private_storage(self):
        other = Backend(1001, self.root / 'state', self.root / 'run', self.root / 'netns')
        self.assertNotEqual(self.backend.namespace('test'), other.namespace('test'))
        self.assertEqual(self.backend.path('test').stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileNotFoundError):
            other.status('test')

    def test_unknown_rpc_fields_rejected(self):
        for request in ({'op': 'shell'}, {'op': 'status', 'profile': 'test', 'uid': 0}, {'op': 'list', 'path': '/etc/shadow'}):
            with self.assertRaises(ValueError):
                dispatch(self.backend, request, [])

    def test_failed_start_rolls_back(self):
        calls = []
        def fake(*args, **kwargs):
            calls.append(args)
            if args[:3] == ('/usr/bin/wg', 'setconf', args[2]):
                raise RuntimeError('injected')
            return ''
        with patch('appwire.backend.command', side_effect=fake), self.assertRaises(RuntimeError):
            self.backend.start('test')
        self.assertTrue(any(c[1:3] == ('link', 'del') for c in calls))
        self.assertTrue(any(c[1:3] == ('netns', 'del') for c in calls))
        self.assertFalse(any('route' in c for c in calls))

    def test_stop_removes_wireguard_before_namespace(self):
        (self.backend.netns / self.backend.namespace('test')).touch()
        calls = []
        def fake(*args, **kwargs):
            calls.append(args)
            return '[{"ifname":"lo"},{"ifname":"wg0"}]' if '-j' in args else ''
        with patch('appwire.backend.command', side_effect=fake):
            self.backend.stop('test')
        self.assertEqual(calls[-2][-3:], ('link', 'del', 'wg0'))
        self.assertEqual(calls[-1][1:3], ('netns', 'del'))

    def test_unexpected_nic_refuses_launch(self):
        with patch('appwire.backend.command', return_value='[{"ifname":"lo"},{"ifname":"wg0"},{"ifname":"eth0"}]'), patch('appwire.daemon.spawn') as spawn:
            with self.assertRaises(RuntimeError):
                dispatch(self.backend, {'op': 'run', 'profile': 'test', 'argv': ['/bin/true'], 'env': {}}, [])
            spawn.assert_not_called()

    def test_no_root_launches(self):
        self.assertFalse(authorized(0))

    def test_active_profile_cannot_be_replaced(self):
        (self.backend.netns / self.backend.namespace('test')).touch()
        with self.assertRaises(ValueError):
            self.backend.import_config('test', CONFIG)
        with self.assertRaises(ValueError):
            self.backend.remove('test')

    def test_status_never_requests_secret_dump(self):
        (self.backend.netns / self.backend.namespace('test')).touch()
        def fake(*args, **kwargs):
            if '-j' in args:
                return '[{"ifname":"lo"},{"ifname":"wg0"}]'
            if args[-1] == 'latest-handshakes':
                return PUBLIC + '\t0\n'
            if args[-1] == 'transfer':
                return PUBLIC + '\t123\t456\n'
            if args[-1] == 'endpoints':
                return PUBLIC + '\t192.0.2.1:51820\n'
            return PUBLIC
        with patch('appwire.backend.command', side_effect=fake) as command:
            result = self.backend.status('test')
        self.assertEqual(result['namespace_inode'], (self.backend.netns / self.backend.namespace('test')).stat().st_ino)
        self.assertEqual(result['health'], 'no-recent-handshake')
        self.assertEqual(result['peers'][0]['received'], 123)
        self.assertNotIn(KEY, json.dumps(result))
        self.assertFalse(any('dump' in c.args for c in command.call_args_list))


class AuthorizationTests(unittest.TestCase):
    def test_membership_comes_from_system_account_not_client(self):
        with patch('appwire.daemon.pwd.getpwuid', return_value=SimpleNamespace(pw_name='alice', pw_gid=1000)), patch('appwire.daemon.grp.getgrnam', return_value=SimpleNamespace(gr_gid=987)), patch('appwire.daemon.os.getgrouplist', return_value=[1000, 987]):
            self.assertTrue(authorized(1000))
        with patch('appwire.daemon.pwd.getpwuid', return_value=SimpleNamespace(pw_name='alice', pw_gid=1000)), patch('appwire.daemon.grp.getgrnam', return_value=SimpleNamespace(gr_gid=987)), patch('appwire.daemon.os.getgrouplist', return_value=[1000]):
            self.assertFalse(authorized(1000))


class ProcessListingTests(unittest.TestCase):
    def test_protected_namespace_handle_is_never_read_by_client(self):
        original_stat = os.stat
        calls = []
        inode = original_stat('/proc/self/ns/net').st_ino
        def protected_stat(path, *args, **kwargs):
            calls.append(str(path))
            if str(path).startswith('/run/netns'):
                raise PermissionError('Protected namespace directory')
            return original_stat(path, *args, **kwargs)
        status = {'state': 'up', 'namespace': 'aw-1000-test', 'namespace_inode': inode}
        with patch('appwire.client.os.stat', side_effect=protected_stat):
            add_applications(status)
        self.assertIn(os.getpid(), [p['pid'] for p in status['applications']])
        self.assertFalse(any(p.startswith('/run/netns') for p in calls))

    def test_missing_identity_does_not_fall_back_to_namespace_path(self):
        status = {'state': 'up', 'namespace': 'aw-1000-test'}
        with patch('appwire.client.os.stat', side_effect=AssertionError('Unexpected stat')):
            add_applications(status)
        self.assertEqual(status['applications'], [])


class LaunchTests(unittest.TestCase):
    def test_socket_stdio_refused(self):
        a, b = socket.socketpair()
        directory = os.open('.', os.O_RDONLY | os.O_DIRECTORY)
        try:
            with self.assertRaises(ValueError):
                validate_launch({'argv': ['true'], 'env': {}}, [a.fileno(), a.fileno(), a.fileno(), directory])
        finally:
            a.close()
            b.close()
            os.close(directory)

    def test_env_and_argv_validation(self):
        for req in ({'argv': [], 'env': {}}, {'argv': ['true'], 'env': {'BAD=KEY': 'x'}}, {'argv': ['a\0b'], 'env': {}}):
            with self.assertRaises(ValueError):
                validate_launch(req, [])


if __name__ == '__main__':
    unittest.main()
