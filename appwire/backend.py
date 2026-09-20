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
import uuid

from .config import parse, profile_name

ENV = {'PATH': '/usr/bin', 'LANG': 'C', 'WG_ENDPOINT_RESOLUTION_RETRIES': '0'}


class OperationError(RuntimeError):
    def __init__(self, stage, detail):
        self.code = stage
        super().__init__(f'{stage.replace("_", " ").capitalize()}: {detail}. Run appwire doctor; raw tool output is withheld to protect keys')


def command(*args, input=None, check=True):
    # Derive stages only from fixed verb positions, never from supplied values.
    if args[0] == '/usr/bin/wg' and args[1:2] == ('setconf',):
        stage = 'configure_wireguard'
    elif args[1:3] == ('netns', 'add'):
        stage = 'create_namespace'
    elif args[1:3] == ('netns', 'del'):
        stage = 'remove_namespace'
    elif args[1:3] == ('link', 'add'):
        stage = 'create_wireguard_interface'
    elif len(args) > 4 and args[1] == '-n' and args[3] in ('-4', '-6'):
        stage = 'configure_tunnel_routes'
    else:
        stage = 'inspect_or_configure_namespace'
    try:
        result = subprocess.run(args, input=input, text=True, capture_output=True, env=ENV, timeout=20)
    except subprocess.TimeoutExpired:
        raise OperationError(stage, 'operation timed out') from None
    except FileNotFoundError:
        raise OperationError(stage, 'required system tool is missing') from None
    if check and result.returncode:
        raise OperationError(stage, f'tool exited with status {result.returncode}')
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

    def import_config(self, name, text, replace=False):
        parse(text)
        path = self.path(name)
        if not path.exists() and len(list(self.root.glob('*.conf'))) >= 32:
            raise ValueError('Maximum 32 profiles per user')
        if self.exists(name):
            raise ValueError('Stop this profile before replacing its configuration')
        if path.exists() and not replace:
            raise ValueError('Profile already exists; explicitly choose replacement or another name')
        atomic(path, text)
        return {'profile': name, 'state': 'imported'}

    def remove(self, name):
        if self.exists(name):
            raise ValueError('Stop this profile before removing it')
        self.path(name).unlink()
        return {'profile': name, 'state': 'removed'}

    def rename(self, name, new_name):
        source, target = self.path(name), self.path(new_name)
        if self.exists(name) or self.exists(new_name):
            raise ValueError('Stop the profile before renaming it')
        if target.exists():
            raise ValueError('The new profile name already exists')
        source.rename(target)
        return {'profile': new_name, 'state': 'renamed'}

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
            atomic(directory / 'generation', str(uuid.uuid4()))
        except Exception:
            if made_if and not moved:
                with contextlib.suppress(OSError, RuntimeError, subprocess.SubprocessError):
                    command('/usr/bin/ip', 'link', 'del', temporary_if, check=False)
            if made_ns:
                with contextlib.suppress(OSError, RuntimeError, subprocess.SubprocessError):
                    command('/usr/bin/ip', 'netns', 'del', ns, check=False)
            raise
        return self.status(name)

    def verify(self, name):
        if not self.exists(name):
            raise RuntimeError('Profile is stopped. Start it before launching or checking its exit IP')
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
        # Publish identity, not a namespace descriptor or access permissions.
        result['namespace_inode'] = (self.netns / ns).stat().st_ino
        generation = self.runtime / ns / 'generation'
        result['generation'] = generation.read_text() if generation.exists() else str(result['namespace_inode'])
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
        profiles = []
        for path in sorted(self.root.glob('*.conf')):
            try:
                profiles.append(self.status(path.stem))
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                profiles.append({'profile': path.stem, 'state': 'error', 'peers': [],
                                 'error': 'Cannot inspect this profile; inspect service diagnostics before recovery'})
        return profiles
