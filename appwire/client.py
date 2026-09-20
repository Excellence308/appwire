"""Unprivileged service client."""
import ipaddress
import os
from pathlib import Path
import signal
import socket
import tempfile

from .protocol import SOCKET, receive, send


def connect():
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    sock.settimeout(120)
    try:
        sock.connect(SOCKET)
    except (FileNotFoundError, ConnectionRefusedError) as error:
        sock.close()
        raise RuntimeError('AppWire service is unavailable. Run appwire setup in a terminal to enable startup, then Retry. Saved profiles have not been deleted.') from error
    except PermissionError as error:
        sock.close()
        raise RuntimeError('Access denied. Run appwire doctor to check appwire group membership. After joining the group, log out of the desktop and back in; a new terminal alone may not refresh desktop permissions.') from error
    except OSError:
        sock.close()
        raise
    return sock


def response(sock):
    result, fds = receive(sock)
    for fd in fds:
        os.close(fd)
    if fds:
        raise RuntimeError('Unexpected descriptors from service')
    if not result.get('ok'):
        raise RuntimeError(result.get('error', 'Service request failed'))
    return result


def call(op, **values):
    with connect() as sock:
        send(sock, {'op': op, **values})
        result = response(sock)
        for item in result.get('profiles', [result]):
            add_applications(item)
        return result


def add_applications(status):
    # Inspect as the caller: the root broker does not need CAP_SYS_PTRACE.
    status['applications'] = []
    if status.get('state') != 'up' or 'namespace' not in status:
        return
    target = status.get('namespace_inode')
    if type(target) is not int or target <= 0:
        return
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal():
            continue
        try:
            if process.stat().st_uid == os.getuid() and (process / 'ns/net').stat().st_ino == target:
                status['applications'].append({'pid': int(process.name), 'name': (process / 'comm').read_text().strip()})
        except OSError:
            continue


def run(profile, argv, streams=(0, 1, 2), forward_signals=True):
    directory = os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    old_handlers = {}
    try:
        with connect() as sock:
            send(sock, {'op': 'run', 'profile': profile, 'argv': argv, 'env': dict(os.environ)}, (*streams, directory))
            result = response(sock)
            if 'started' not in result:
                raise RuntimeError('Service did not confirm application launch')
            sock.settimeout(None)
            if forward_signals:
                def forward(signum, _frame):
                    try:
                        send(sock, {'signal': signum})
                    except OSError:
                        pass
                for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                    old_handlers[signum] = signal.signal(signum, forward)
            return response(sock)['exit_code']
    finally:
        os.close(directory)
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)


def probe(profile, ipv6=False):
    # Fixed HTTPS endpoint; curl runs as caller INSIDE namespace, never as root.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors, open('/dev/null', 'rb') as source:
        code = run(profile, ['/usr/bin/curl', '-q', '-6' if ipv6 else '-4', '--proxy', '', '--noproxy', '*', '--proto', '=https', '--max-time', '12', '--fail', '--silent', '--show-error', 'https://api64.ipify.org'], (source.fileno(), output.fileno(), errors.fileno()), forward_signals=False)
        output.seek(0)
        if code:
            raise RuntimeError('Exit-IP probe failed inside tunnel; no host fallback was attempted')
        return str(ipaddress.ip_address(output.read(128).decode().strip()))
