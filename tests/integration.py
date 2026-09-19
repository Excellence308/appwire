#!/usr/bin/env python
"""Run ONLY via tests/integration.sh in disposable user/mount/net namespaces."""
import ctypes
import json
import os
from pathlib import Path
import pwd
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from appwire.backend import Backend, command
from appwire.launch import spawn, mount, MS_BIND
import appwire.launch as launch_module
original_checked = launch_module.checked
def debug_checked(result):
    if result != 0:
        import traceback
        os.write(2, ('native failure errno=' + str(ctypes.get_errno()) + '\n' + ''.join(traceback.format_stack())).encode())
    original_checked(result)
launch_module.checked = debug_checked

assert os.getuid() == 0 and os.environ.get('APPWIRE_TEST_ISOLATED') == '1'
libc = ctypes.CDLL(None, use_errno=True)
root = Path(tempfile.mkdtemp(prefix='appwire-integration-'))
(root / 'netns').mkdir()
(root / 'runtime').mkdir()
# Replace /run privately; the sandbox's host /run is intentionally read-only.
resolver_target = Path('/etc/resolv.conf').resolve()
resolver_text = Path('/etc/resolv.conf').read_text()
subprocess.run(['/usr/bin/mount', '-t', 'tmpfs', 'tmpfs', '/run'], check=True)
if str(resolver_target).startswith('/run/'):
    resolver_target.parent.mkdir(parents=True, exist_ok=True)
    resolver_target.write_text(resolver_text)
Path('/run/netns').mkdir(exist_ok=True)
mount(str(root / 'netns'), '/run/netns', MS_BIND)
# Arch sandbox may hide these mount targets; use real host resolver target.


def check(value, description):
    assert value, description
    print('PASS:', description, flush=True)


def generate_key():
    private = command('/usr/bin/wg', 'genkey').strip()
    public = command('/usr/bin/wg', 'pubkey', input=private).strip()
    return private, public


server_private, server_public = generate_key()
client_private, client_public = generate_key()
command('/usr/bin/ip', 'link', 'set', 'lo', 'up')
command('/usr/bin/ip', 'link', 'add', 'wgpeer', 'type', 'wireguard')
server_config = f'[Interface]\nPrivateKey = {server_private}\nListenPort = 51829\n[Peer]\nPublicKey = {client_public}\nAllowedIPs = 10.20.0.2/32, fd20::2/128\n'
command('/usr/bin/wg', 'setconf', 'wgpeer', '/dev/stdin', input=server_config)
command('/usr/bin/ip', 'address', 'add', '10.20.0.1/24', 'dev', 'wgpeer')
command('/usr/bin/ip', '-6', 'address', 'add', 'fd20::1/64', 'dev', 'wgpeer')
command('/usr/bin/ip', 'link', 'set', 'wgpeer', 'up')
# A host-only endpoint deliberately outside the tunnel.
command('/usr/bin/ip', 'address', 'add', '198.18.0.1/32', 'dev', 'lo')
def route_snapshot(ipv6=False):
    args = ['/usr/bin/ip'] + (['-6'] if ipv6 else []) + ['-j', 'route', 'show', 'table', 'all']
    return sorted(json.dumps(x, sort_keys=True) for x in json.loads(command(*args)))
original_routes = route_snapshot()
original_routes6 = route_snapshot(True)
config = f'''[Interface]
PrivateKey = {client_private}
Address = 10.20.0.2/32, fd20::2/128
DNS = 10.20.0.1
[Peer]
PublicKey = {server_public}
Endpoint = 127.0.0.1:51829
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 1
'''
backend = Backend(0, root / 'state', root / 'runtime')
backend.import_config('test', config)
backend.start('test')
ns = backend.namespace('test')
check(original_routes == route_snapshot(), 'birthplace IPv4 routes unchanged')
check(original_routes6 == route_snapshot(True), 'birthplace IPv6 routes unchanged')
check({x['ifname'] for x in json.loads(command('/usr/bin/ip', '-n', ns, '-j', 'link'))} == {'lo', 'wg0'}, 'only loopback and WireGuard visible')
# ping replies from the encrypted peer exercise both families.
command('/usr/bin/ip', 'netns', 'exec', ns, '/usr/bin/ping', '-c', '1', '-W', '3', '10.20.0.1')
command('/usr/bin/ip', 'netns', 'exec', ns, '/usr/bin/ping', '-6', '-c', '1', '-W', '3', 'fd20::1')
status = backend.status('test')
check(status['health'] == 'recent-handshake', 'real WireGuard handshake')
check(status['peers'][0]['received'] > 0 and status['peers'][0]['sent'] > 0, 'real transfer counters')
check(client_private not in json.dumps(status) and server_private not in json.dumps(status), 'status excludes private keys')

# Local DNS server reached ONLY across WireGuard.
dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
dns.bind(('10.20.0.1', 53))
dns.settimeout(0.5)
stop_dns = threading.Event()
queries = []
def serve_dns():
    while not stop_dns.is_set():
        try:
            data, addr = dns.recvfrom(4096)
        except socket.timeout:
            continue
        queries.append(addr)
        end = 12
        while data[end]:
            end += data[end] + 1
        end += 1
        qtype = struct.unpack('!H', data[end:end + 2])[0]
        question = data[12:end + 4]
        payload = socket.inet_pton(socket.AF_INET6 if qtype == 28 else socket.AF_INET, 'fd20::1' if qtype == 28 else '10.20.0.1')
        answer = b'\xc0\x0c' + struct.pack('!HHIH', qtype, 1, 30, len(payload)) + payload
        dns.sendto(data[:2] + b'\x81\x80' + struct.pack('!HHHH', 1, 1, 0, 0) + question + answer, addr)
threading.Thread(target=serve_dns, daemon=True).start()

# The unprivileged sandbox can map only one UID. Exercise the real launch path
# using namespace-root with *all* capabilities removed; skip setgroups because
# the outer kernel mapping explicitly denies it. Production rejects uid 0.
account = pwd.struct_passwd(('isolated-test', 'x', 0, 0, '', '/tmp', '/bin/sh'))
def launch_python(code):
    output = tempfile.TemporaryFile()
    errors = tempfile.TemporaryFile()
    source = open('/dev/null', 'rb')
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with patch('appwire.launch.pwd.getpwuid', return_value=account), patch('appwire.launch.os.getgrouplist', return_value=[]), patch('appwire.launch.os.setgroups'):
            try:
                process = spawn(backend, 'test', {'argv': ['/usr/bin/python', '-c', code], 'env': {'PATH': '/usr/bin'}}, [source.fileno(), output.fileno(), errors.fileno(), directory])
            except Exception:
                errors.seek(0)
                print(errors.read().decode(), flush=True)
                raise
        return process, output, errors
    finally:
        source.close()
        os.close(directory)

code = '''import json, os, socket
from pathlib import Path
status = Path('/proc/self/status').read_text()
print(json.dumps({'dns': socket.gethostbyname('probe.appwire.test'), 'ns': os.readlink('/proc/self/ns/net'), 'resolv': Path('/etc/resolv.conf').read_text(), 'nss': Path('/etc/nsswitch.conf').read_text(), 'status': status, 'cwd': os.getcwd(), 'fds': {x: os.readlink('/proc/self/fd/'+x) for x in os.listdir('/proc/self/fd') if os.path.exists('/proc/self/fd/'+x)}}), flush=True)
'''
p, output, errors = launch_python(code)
rc = p.wait(timeout=10)
errors.seek(0)
check(rc == 0, 'app launch and DNS lookup: ' + errors.read().decode())
output.seek(0)
result = json.loads(output.read())
check(result['dns'] == '10.20.0.1' and queries and queries[0][0] == '10.20.0.2', 'DNS query originated from tunnel address')
check('hosts: files dns' in result['nss'] and 'nameserver 10.20.0.1' in result['resolv'], 'private DNS and NSS mounts applied')
check('CapEff:\t0000000000000000' in result['status'] and 'CapPrm:\t0000000000000000' in result['status'] and 'CapBnd:\t0000000000000000' in result['status'] and 'NoNewPrivs:\t1' in result['status'], 'application has zero capabilities and no-new-privileges')
check(set(result['fds']) == {'0', '1', '2'}, 'no privileged namespace or host socket descriptors inherited')
check(result['cwd'] == str(root), 'caller working directory retained')
output.close(); errors.close()

command('/usr/bin/wg', 'set', 'wgpeer', 'listen-port', '51830')
for target, family in [('10.20.0.1', '-4'), ('fd20::1', '-6')]:
    result = command('/usr/bin/ip', 'netns', 'exec', ns, '/usr/bin/ping', family, '-c', '1', '-W', '1', target, check=False)
    check(result != 0, f'peer outage blocks {family} traffic with no fallback')
command('/usr/bin/wg', 'set', 'wgpeer', 'listen-port', '51829')


# Keep a real app alive across down/start and test it stays on old isolated netns.
ready, proceed, report = root / 'ready', root / 'proceed', root / 'report'
code = f'''import os, socket, time, json
from pathlib import Path
Path({str(ready)!r}).write_text(os.readlink('/proc/self/ns/net'))
while not Path({str(proceed)!r}).exists(): time.sleep(.05)
results = {{}}
for family, host in ((socket.AF_INET, '10.20.0.1'), (socket.AF_INET6, 'fd20::1'), (socket.AF_INET, '198.18.0.1')):
    s = socket.socket(family, socket.SOCK_DGRAM)
    try:
        s.connect((host, 53)); s.send(b'test'); results[host] = 'sent'
    except OSError: results[host] = 'blocked'
    s.close()
Path({str(report)!r}).write_text(json.dumps(results))
'''
p, output, errors = launch_python(code)
for _ in range(100):
    if ready.exists(): break
    time.sleep(.02)
check(ready.exists(), 'long-running application entered namespace')
old_inode = ready.read_text()
backend.stop('test')
backend.start('test')
new_inode = command('/usr/bin/ip', 'netns', 'exec', ns, '/usr/bin/readlink', '/proc/self/ns/net').strip()
check(old_inode != new_inode, 'restart creates a distinct namespace generation')
proceed.touch()
check(p.wait(timeout=10) == 0, 'existing app survived disconnect')
check(set(json.loads(report.read_text()).values()) == {'blocked'}, 'existing app blocked for IPv4, IPv6 and host-only address after stop/restart')
backend.stop('test')
check(not backend.exists('test'), 'namespace cleanup')
if original_routes != route_snapshot():
    print('Route difference:', set(original_routes) ^ set(route_snapshot()), flush=True)
check(original_routes == route_snapshot(), 'birthplace routes unchanged after lifecycle')
stop_dns.set()
output.close(); errors.close()
print('All isolated kernel integration checks passed. No production VPN or host routing touched.')
