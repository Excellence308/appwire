"""Root service: peer-credential authorization, per-user profiles, bounded RPC."""
import grp
import os
from pathlib import Path
import pwd
import select
import signal
import socket
import struct
import sys

from .backend import Backend
from .launch import spawn
from .protocol import SOCKET, receive, send


def authorized(uid):
    if uid == 0:
        return False  # Apps must belong to an ordinary user, never root.
    account = pwd.getpwuid(uid)
    group = grp.getgrnam('appwire').gr_gid
    return group in os.getgrouplist(account.pw_name, account.pw_gid)


def dispatch(backend, request, fds):
    op = request.get('op')
    fields = {'list': set(), 'import': {'profile', 'config'}, 'remove': {'profile'}, 'start': {'profile'}, 'stop': {'profile'}, 'status': {'profile'}, 'run': {'profile', 'argv', 'env'}}
    if op not in fields or set(request) != fields[op] | {'op'}:
        raise ValueError('Unknown operation or unexpected request fields')
    if op != 'run' and fds:
        raise ValueError('Unexpected file descriptors')
    with backend.locked():
        if op == 'list':
            return {'profiles': backend.profiles()}
        name = request['profile']
        if op == 'import':
            return backend.import_config(name, request['config'])
        if op == 'run':
            # Explicit start is required. Failure never launches on host.
            backend.path(name).stat()
            backend.verify(name)
            # Popen returns after pre-exec and exec have completed. Stop cannot
            # race namespace entry because it uses the same lock.
            return spawn(backend, name, request, fds)
        return getattr(backend, op)(name)


def serve_connection(conn):
    fds = []
    proc = None
    try:
        _, uid, _ = struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if not authorized(uid):
            raise PermissionError('Your account must be a member of appwire; root launches are refused')
        conn.settimeout(5)
        request, fds = receive(conn)
        result = dispatch(Backend(uid), request, fds)
        for fd in fds:
            os.close(fd)
        fds = []
        conn.settimeout(None)
        if isinstance(result, dict):
            send(conn, {'ok': True, **result})
            return
        proc = result
        send(conn, {'ok': True, 'started': proc.pid})
        while proc.poll() is None:
            if select.select([conn], [], [], 0.2)[0]:
                message, extra = receive(conn)
                for fd in extra:
                    os.close(fd)
                if extra or set(message) != {'signal'} or type(message['signal']) is not int or message['signal'] not in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                    raise ValueError('Invalid signal request')
                try:
                    os.killpg(proc.pid, message['signal'])
                except ProcessLookupError:
                    pass
        send(conn, {'ok': True, 'exit_code': proc.returncode if proc.returncode >= 0 else 128 - proc.returncode})
    except Exception as error:
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=3)
            except Exception:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            # Exception strings for config validation / OS errors have no keys.
            # SubprocessError may include argv; keep these generic.
            message = str(error) if isinstance(error, (ValueError, PermissionError, FileNotFoundError, RuntimeError)) else 'Operation failed; check service journal and dependencies'
            send(conn, {'ok': False, 'error': message})
        except OSError:
            pass
    finally:
        for fd in fds:
            os.close(fd)
        conn.close()


def main():
    if os.geteuid() != 0:
        sys.exit('appwired must run as the system service')
    os.umask(0o077)
    os.environ.clear()
    os.environ.update(PATH='/usr/bin', LANG='C')
    Path('/run/appwire').mkdir(mode=0o755, exist_ok=True)
    Path('/var/lib/appwire').mkdir(mode=0o700, exist_ok=True)
    # Exclusive daemon lock protects against a second process unlinking our socket.
    import fcntl
    lock = open('/run/appwire/daemon.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    Path(SOCKET).unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC)
    server.bind(SOCKET)
    os.chown(SOCKET, 0, grp.getgrnam('appwire').gr_gid)
    os.chmod(SOCKET, 0o660)
    server.listen(32)
    server.settimeout(1)
    children = set()
    try:
        while True:
            for pid in list(children):
                if os.waitpid(pid, os.WNOHANG)[0]:
                    children.remove(pid)
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            if len(children) >= 64:
                conn.close()
                continue
            pid = os.fork()
            if pid == 0:
                server.close()
                lock.close()
                serve_connection(conn)
                os._exit(0)
            children.add(pid)
            conn.close()
    finally:
        server.close()


if __name__ == '__main__':
    main()
