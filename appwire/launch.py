"""Namespace entry and irreversible credential drop before exec."""
import ctypes
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess

libc = ctypes.CDLL(None, use_errno=True)
CLONE_NEWNS = 0x00020000
CLONE_NEWNET = 0x40000000
MS_BIND, MS_REC, MS_PRIVATE, MS_REMOUNT, MS_RDONLY = 4096, 16384, 1 << 18, 32, 1


def checked(result):
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def mount(source, target, flags):
    checked(libc.mount(source.encode() if source else None, str(target).encode(), None, ctypes.c_ulong(flags), None))


def validate_launch(request, fds):
    argv, env = request.get('argv'), request.get('env')
    if not isinstance(argv, list) or not 1 <= len(argv) <= 256 or any(not isinstance(x, str) or '\0' in x or len(x) > 16384 for x in argv) or not argv[0]:
        raise ValueError('Invalid application arguments')
    if not isinstance(env, dict) or len(env) > 256 or any(not isinstance(k, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', k) or not isinstance(v, str) or '\0' in v or len(v) > 16384 for k, v in env.items()):
        raise ValueError('Invalid application environment')
    if len(fds) != 4 or not stat.S_ISDIR(os.fstat(fds[3]).st_mode):
        raise ValueError('Launch requires stdin, stdout, stderr and working-directory descriptors')
    for fd in fds[:3]:
        if stat.S_ISSOCK(os.fstat(fd).st_mode):
            raise ValueError('Socket standard streams are forbidden: they could retain host networking')
    return argv, env


def spawn(backend, name, request, fds):
    argv, env = validate_launch(request, fds)
    account = pwd.getpwuid(backend.uid)
    groups = os.getgrouplist(account.pw_name, account.pw_gid)
    env = dict(env)
    env.update(HOME=account.pw_dir, USER=account.pw_name, LOGNAME=account.pw_name)
    env.setdefault('PATH', '/usr/local/bin:/usr/bin')
    ns = backend.namespace(name)
    nsfd = os.open(backend.netns / ns, os.O_RDONLY | os.O_CLOEXEC)
    directory = backend.runtime / ns

    def enter():
        checked(libc.setns(nsfd, CLONE_NEWNET))
        checked(libc.unshare(CLONE_NEWNS))
        mount(None, '/', MS_REC | MS_PRIVATE)
        for filename in ('resolv.conf', 'nsswitch.conf'):
            destination = Path('/etc') / filename
            # Targets and sources are root-controlled, never client paths.
            mount(str(directory / filename), destination, MS_BIND)
            # Preserve inherited mount restrictions (including userns-locked
            # nosuid/nodev/noexec and atime flags) on the bind remount.
            flags = os.statvfs(destination).f_flag
            inherited = flags & (2 | 4 | 8 | 16 | 64 | 1024 | 2048)
            if flags & getattr(os, 'ST_RELATIME', 4096):
                inherited |= 1 << 21
            mount(None, destination, MS_BIND | MS_REMOUNT | MS_RDONLY | inherited)
        os.setsid()
        checked(libc.prctl(38, 1, 0, 0, 0))  # PR_SET_NO_NEW_PRIVS
        # Clear the bounding set before dropping uid; no file capabilities later.
        for capability in range(int(Path('/proc/sys/kernel/cap_last_cap').read_text()) + 1):
            checked(libc.prctl(24, capability, 0, 0, 0))  # PR_CAPBSET_DROP
        os.setgroups(groups)
        os.setresgid(account.pw_gid, account.pw_gid, account.pw_gid)
        os.setresuid(account.pw_uid, account.pw_uid, account.pw_uid)
        # Explicitly clear effective/permitted/inheritable capabilities too.
        class Header(ctypes.Structure):
            _fields_ = [('version', ctypes.c_uint32), ('pid', ctypes.c_int)]
        class Data(ctypes.Structure):
            _fields_ = [('effective', ctypes.c_uint32), ('permitted', ctypes.c_uint32), ('inheritable', ctypes.c_uint32)]
        header, data = Header(0x20080522, 0), (Data * 2)()
        checked(libc.capset(ctypes.byref(header), ctypes.byref(data)))
        os.umask(0o022)
        os.fchdir(fds[3])
        # Popen closes nsfd and cwd before exec. Only caller stdio survives.

    try:
        return subprocess.Popen(argv, env=env, stdin=fds[0], stdout=fds[1], stderr=fds[2], preexec_fn=enter, close_fds=True)
    finally:
        os.close(nsfd)
