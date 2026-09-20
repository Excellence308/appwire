#!/usr/bin/bash
# Install the built local package without interrupting existing AppWire apps.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
package="$repo/appwire-0.2.1-1-any.pkg.tar.zst"
if [[ ! -f "$package" ]]; then
    printf '%s\n' "Build the package first: cd '$repo' && makepkg -f" >&2
    exit 1
fi
if systemctl is-active --quiet appwire.service; then
    broker=$(systemctl show appwire.service -p MainPID --value)
    group=$(systemctl show appwire.service -p ControlGroup --value)
    if [[ ! "$group" =~ ^/system.slice/appwire.service(/|$) ]] || [[ ! -r "/sys/fs/cgroup$group/cgroup.procs" ]]; then
        printf '%s\n' 'Cannot verify service applications. Close them and perform the upgrade manually.' >&2
        exit 1
    fi
    mapfile -t pids < <(find "/sys/fs/cgroup$group" -name cgroup.procs -exec cat {} +)
    for pid in "${pids[@]}"; do
        if [[ "$pid" != "$broker" ]]; then
            printf '%s\n' 'AppWire still has applications or requests running. Close its apps and GUI, then retry.' >&2
            exit 1
        fi
    done
    printf '%s\n' 'No service applications found. Stopping the broker for maintenance; do not launch apps during installation.'
    sudo systemctl stop appwire.service
fi
sudo pacman -U -- "$package"
appwire setup
appwire doctor
printf '%s\n' 'Reopen AppWire. If newly enrolled in the group, log out and back in first.'
