"""Small unprivileged helpers for import, installation and launch output."""
import grp
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
from . import __version__


def directory():
    path = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'appwire'
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def suggested_name(filename):
    stem = Path(filename).stem.lower()
    # Proton exports sometimes append US-CA-245 to proton-us-ca-245.
    match = re.fullmatch(r'(.*?)(us-[a-z]{2}-\d+)-\2', stem)
    if match:
        stem = match[1] + match[2]
    return re.sub(r'[^a-z0-9-]+', '-', stem).strip('-')[:32] or 'profile'


def doctor():
    from . import client
    account = pwd.getpwuid(os.getuid())
    result = {'client_version': __version__, 'checks': {},
              'note': 'Read-only checks in this process environment; no connectivity or isolation test was performed.'}
    checks = result['checks']
    for tool in ('ip', 'wg', 'curl', 'systemctl', 'ss'):
        checks['tool_' + tool] = bool(shutil.which(tool))
    try:
        gid = grp.getgrnam('appwire').gr_gid
        checks['account_in_group'] = gid in os.getgrouplist(account.pw_name, account.pw_gid)
        checks['session_in_group'] = gid in [os.getgid(), *os.getgroups()]
    except KeyError:
        checks['account_in_group'] = checks['session_in_group'] = False
    for operation in ('is-active', 'is-enabled'):
        try:
            status = subprocess.run(['/usr/bin/systemctl', operation, 'appwire.service'], capture_output=True, text=True, timeout=5)
            checks[operation] = status.stdout.strip() or 'unavailable in this environment'
        except (OSError, subprocess.SubprocessError):
            checks[operation] = 'unavailable in this environment'
    try:
        info = client.call('info')
        result['broker_version'] = info['version']
        checks['versions_match'] = info['version'] == __version__
        checks['broker_access'] = True
    except (OSError, RuntimeError, ValueError) as error:
        checks['broker_access'] = False
        if 'Unknown operation or unexpected request fields' in str(error):
            checks['broker_access'] = True
            checks['versions_match'] = False
            result['broker_version'] = 'older protocol (no version endpoint)'
            result['recovery'] = 'An older broker is running. After installing this release, close its apps, restart appwire.service and reopen the GUI.'
        else:
            result['recovery'] = str(error)
    checks['runtime_directory'] = Path('/run/appwire').is_dir()
    checks['nsswitch_present'] = Path('/etc/nsswitch.conf').is_file()
    checks['proc_namespace_readable'] = os.access('/proc/self/ns/net', os.R_OK)
    result['setup'] = 'Run appwire setup in a terminal; log out and back in after new group membership.'
    result['maintenance'] = 'Restarting appwire.service terminates its running applications. Close them before upgrades or maintenance.'
    return result


def setup():
    if os.geteuid() == 0:
        raise ValueError('Run appwire setup as your ordinary desktop user; sudo is requested only for fixed setup commands')
    name = pwd.getpwuid(os.getuid()).pw_name
    commands = [['/usr/bin/systemd-sysusers', '/usr/lib/sysusers.d/appwire.conf'],
                ['/usr/bin/usermod', '-a', '-G', 'appwire', name],
                ['/usr/bin/systemctl', 'enable', '--now', 'appwire.service']]
    for command in commands:
        subprocess.run(['/usr/bin/sudo', *command], check=True)
    return 'Service enabled for boot. Log out of your desktop and back in if group membership was newly added. No VPN profile was started.'


def append_log(data):
    """Bound the shared application log even while applications keep running."""
    import fcntl
    directory_path = directory()
    fd = os.open(directory_path / 'log.lock', os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        log = directory_path / 'applications.log'
        for offset in range(0, len(data), 65536):
            chunk = data[offset:offset + 65536]
            if log.exists() and log.stat().st_size + len(chunk) > 2 * 1024 * 1024:
                os.replace(log, directory_path / 'applications.previous.log')
            with os.fdopen(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'ab') as stream:
                stream.write(chunk)
    finally:
        os.close(fd)


def logged_launch(profile, argv):
    from . import client
    import threading
    reader, writer = os.pipe()
    def drain():
        try:
            while chunk := os.read(reader, 65536):
                try:
                    append_log(chunk)
                except OSError:
                    pass  # Keep draining; a full disk must not block the application.
        finally:
            os.close(reader)
    thread = threading.Thread(target=drain)
    thread.start()
    try:
        return client.run(profile, argv, streams=(0, writer, writer))
    except (OSError, ValueError, RuntimeError) as error:
        append_log(('AppWire launch failed: ' + str(error) + '\n').encode())
        raise
    finally:
        os.close(writer)
        thread.join()

