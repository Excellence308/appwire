"""Privileged operations. No shell, hooks, caller paths or caller environment."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from .config import parse, profile_name

ENV = {'PATH': '/usr/bin', 'LANG': 'C', 'WG_ENDPOINT_RESOLUTION_RETRIES': '0'}


def command(*args, input=None, check=True):
    result = subprocess.run(args, input=input, text=True, capture_output=True, env=ENV, timeout=20)
    if check and result.returncode:
        # wg errors can include secrets. Never return raw tool stderr.
        raise RuntimeError(f'{Path(args[0]).name} operation failed ({result.returncode})')
    return result.stdout if check else result.returncode


def atomic(path, content, mode=0o600):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.new-')
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Backend:
    def __init__(self, uid, root=Path('/var/lib/appwire'), runtime=Path('/run/appwire'), netns=Path('/run/netns')):
        self.uid = uid
        self.root = root / str(uid)
        self.runtime = runtime
        self.netns = netns
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    @contextlib.contextmanager
    def locked(self):
        with (self.runtime / 'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def namespace(self, name):
        return f'aw-{self.uid}-{profile_name(name)}'

    def path(self, name):
        return self.root / (profile_name(name) + '.conf')

    def exists(self, name):
        return (self.netns / self.namespace(name)).exists()

    def import_config(self, name, text):
        parse(text)
        path = self.path(name)
        if not path.exists() and len(list(self.root.glob('*.conf'))) >= 32:
            raise ValueError('Maximum 32 profiles per user')
        if self.exists(name):
            raise ValueError('Stop this profile before replacing its configuration')
        atomic(path, text)
        return {'profile': name, 'state': 'imported'}

    def remove(self, name):
        if self.exists(name):
            raise ValueError('Stop this profile before removing it')
        self.path(name).unlink()
        return {'profile': name, 'state': 'removed'}

    def start(self, name):
        config = parse(self.path(name).read_text())
        ns = self.namespace(name)
        if self.exists(name):
            self.verify(name)
            return self.status(name)
        directory = self.runtime / ns
        directory.mkdir(mode=0o700, exist_ok=True)
        atomic(directory / 'resolv.conf', config.resolver(), 0o644)
        nss = Path('/etc/nsswitch.conf').read_text()
        nss = re.sub(r'^\s*hosts:.*$', 'hosts: files dns', nss, flags=re.M)
        if not re.search(r'^hosts:', nss, re.M):
            nss += '\nhosts: files dns\n'
        atomic(directory / 'nsswitch.conf', nss, 0o644)
        temporary_if = 'aw' + hashlib.sha256(ns.encode()).hexdigest()[:11]
        made_ns = made_if = moved = False
        try:
            command('/usr/bin/ip', 'netns', 'add', ns)
            made_ns = True
            command('/usr/bin/ip', 'link', 'add', temporary_if, 'type', 'wireguard')
            made_if = True
            # Configure in birthplace namespace so endpoint DNS uses host resolver.
            command('/usr/bin/wg', 'setconf', temporary_if, '/dev/stdin', input=config.native())
            command('/usr/bin/ip', 'link', 'set', temporary_if, 'netns', ns)
            moved = True
            command('/usr/bin/ip', '-n', ns, 'link', 'set', temporary_if, 'name', 'wg0')
            command('/usr/bin/ip', '-n', ns, 'link', 'set', 'lo', 'up')
            for addr in config.addresses:
                command('/usr/bin/ip', '-n', ns, 'address', 'add', addr, 'dev', 'wg0')
            command('/usr/bin/ip', '-n', ns, 'link', 'set', 'wg0', 'mtu', str(config.mtu), 'up')
            for route in config.routes:
                command('/usr/bin/ip', '-n', ns, '-6' if ':' in route else '-4', 'route', 'replace', route, 'dev', 'wg0')
            self.verify(name)
        except Exception:
            if made_if and not moved:
                command('/usr/bin/ip', 'link', 'del', temporary_if, check=False)
            if made_ns:
                command('/usr/bin/ip', 'netns', 'del', ns, check=False)
            raise
        return self.status(name)

    def verify(self, name):
        ns = self.namespace(name)
        links = json.loads(command('/usr/bin/ip', '-n', ns, '-j', 'link', 'show'))
        if {x['ifname'] for x in links} != {'lo', 'wg0'}:
            raise RuntimeError('Namespace integrity check failed: unexpected interfaces')
        command('/usr/bin/ip', 'netns', 'exec', ns, '/usr/bin/wg', 'show', 'wg0', 'public-key')

    def stop(self, name):
        ns = self.namespace(name)
        if self.exists(name):
            # Delete the tunnel FIRST. Apps retaining the old namespace get loopback
            # only, even if a new generation is started under the same name.
            links = json.loads(command('/usr/bin/ip', '-n', ns, '-j', 'link', 'show'))
            if any(x['ifname'] == 'wg0' for x in links):
                command('/usr/bin/ip', '-n', ns, 'link', 'del', 'wg0')
            command('/usr/bin/ip', 'netns', 'del', ns)
        return {'profile': name, 'state': 'stopped'}

    def status(self, name):
        self.path(name).stat()
        result = {'profile': name, 'namespace': self.namespace(name), 'state': 'stopped', 'peers': [], 'exit_ip': None}
        if not self.exists(name):
            return result
        self.verify(name)
        ns = self.namespace(name)
        # Never use `wg show dump`: it includes private and preshared keys.
        fields = {}
        for field in ('endpoints', 'latest-handshakes', 'transfer'):
            rows = command('/usr/bin/ip', 'netns', 'exec', ns, '/usr/bin/wg', 'show', 'wg0', field)
            fields[field] = {parts[0]: parts[1:] for line in rows.splitlines() if (parts := line.split())}
        for key, values in fields['latest-handshakes'].items():
            stamp = int(values[0])
            transfer = fields['transfer'].get(key, ['0', '0'])
            result['peers'].append({'public_key': key, 'endpoint': ' '.join(fields['endpoints'].get(key, [])), 'latest_handshake': stamp, 'handshake_age': max(0, int(time.time()) - stamp) if stamp else None, 'received': int(transfer[0]), 'sent': int(transfer[1])})
        result['state'] = 'up'
        result['health'] = 'recent-handshake' if any(p['handshake_age'] is not None and p['handshake_age'] < 180 for p in result['peers']) else 'no-recent-handshake'
        return result

    def profiles(self):
        return [self.status(p.stem) for p in sorted(self.root.glob('*.conf'))]
