# AppWire 0.1 — per-app WireGuard for Arch Linux

A custom MVP, built around Linux's existing WireGuard/network-namespace
architecture. This is not an official Proton, WireGuard or Faugus component.

The GUI and CLI run as you. One root system service handles a narrow set of
requests: import/remove/list/start/stop/status/run. It authenticates the local
user, owns their profiles, enters the chosen namespace, configures private DNS,
and drops all privileges before executing an application.

## Architecture

```
GTK GUI / appwire CLI (your UID)
          │ bounded local Unix socket, peer credentials
          ▼
appwired (root, systemd, appwire-group access)
          ├─ /var/lib/appwire/UID/profile.conf  (root:root 0600)
          ├─ aw-UID-profile network namespace
          │       ├─ lo
          │       └─ wg0  ── encrypted UDP socket born on host ── VPN peer
          └─ private DNS mounts → drop groups/UID/capabilities → application
```

No NetworkManager, veth, forwarding, NAT, host firewall edits, host default-route
changes, setuid executable, sudoers rule, downloaded runner, or shell hooks.
WireGuard's encrypted socket uses the existing host uplink. Cleartext application
traffic sees only `lo` and `wg0`. A stopped or unreachable tunnel provides no
alternative host NIC. IPv6 is tunneled when configured; otherwise it has no
external route. This is traffic isolation for cooperative apps, not a malicious
application sandbox. See [security boundaries](docs/SECURITY.md).

## Build and install on Arch

From this source directory:

```sh
make check
./tests/integration.sh
makepkg -f
sudo pacman -U ./appwire-0.1.0-2-any.pkg.tar.zst
sudo systemd-sysusers
sudo usermod -aG appwire "$USER"
sudo systemctl enable --now appwire.service
```

The GUI additionally needs `python-gobject` and `gtk3`. The package declares
these as optional dependencies. Build requires `make`; runtime dependencies are
listed in `PKGBUILD`. This is a local-source PKGBUILD, not an AUR release recipe.
Log out and back in after group enrollment so desktop launchers inherit it.
Do not run the GUI or CLI with sudo. Import only a readable copy of a config
owned by you. Secrets are never passed on the command line.

`make install DESTDIR=...` supports package staging. The installation prefix is
`/usr` (launchers and unit deliberately use fixed, root-owned paths).

## Use

```sh
appwire import proton-us ~/Downloads/proton-us.conf
appwire start proton-us
appwire status proton-us
appwire probe proton-us
appwire run proton-us -- curl -q --proxy '' https://api.ipify.org
appwire run proton-us -- faugus-launcher
appwire gui
appwire stop proton-us
appwire remove proton-us
```

`start` means the interface and routes are configured, not that the VPN server
has answered. Status separately reports recent/no recent handshake and transfer
counters. `probe` makes a fresh HTTPS request inside the tunnel and prints the
observed IPv4 address; `probe --ipv6` tests IPv6. Probe contacts api64.ipify.org.
A failed probe is an error, never a host-side fallback or a cached success.

Launch is explicit: it fails if the profile is stopped, incomplete, or has an
unexpected interface. Start it first. CLI preserves arguments, environment,
working directory and normal standard streams. Signals INT/TERM/HUP are
forwarded to the launched process group; return status propagates. This MVP
supports command-line tools and desktop apps, but does not implement PTY job
control for interactive shells or full-screen terminal applications. Standard
streams that are sockets are refused because they could carry host networking.

The GUI imports profiles, starts/stops them, refreshes handshake/transfer/process
status, checks IPv4 exit address on demand, and launches a command without shell
expansion. App output goes to `$XDG_STATE_HOME/appwire/applications.log` (default
`~/.local/state/appwire/applications.log`). Closing the GUI leaves launched apps
running. Refresh is every five seconds; network operations never block GTK.

## Faugus / Wine / Battle.net

1. Fully quit the existing Faugus instance, Battle.net and games using the
   intended prefix. An existing Wine server or single-instance launcher may
   reuse a host-side process, so starting another UI is not proof of isolation.
2. Start the profile, then launch the whole chain with
   `appwire run proton-us -- faugus-launcher`.
3. Start Battle.net and WoW normally inside that Faugus instance. Existing
   prefixes/runners/settings are preserved. For simultaneous VPN/non-VPN Wine,
   use separate prefixes and avoid sharing a Wine server between them.
4. Check `appwire status proton-us`: its application list contains only PIDs
   actually in that namespace and belonging to your UID. Confirm the game PID,
   not just the launcher. A host-side single-instance handoff is outside AppWire's
   guarantee; this MVP does not automatically terminate or migrate old processes.

Wayland/X11, audio and session environment remain available. No prefix, desktop
entry, Faugus setting or existing `vpnns`/Veil installation is modified. For a
personal desktop shortcut, set `Exec=appwire run proton-us -- faugus-launcher`
after the profile is started. The existing Faugus prefix is left in place.

Do not run the same provider key simultaneously in the old manager and AppWire:
WireGuard peer roaming can make the two sessions disrupt one another.

## Config support

Ordinary provider wg-quick files with one `[Interface]` and up to 16 `[Peer]`
sections: PrivateKey, Address, DNS, MTU, ListenPort; PublicKey, PresharedKey,
Endpoint, AllowedIPs, PersistentKeepalive. IPv4 and IPv6 addresses/endpoints are
supported. Numeric DNS servers are required and must be covered by AllowedIPs;
search domains are accepted alongside them. Configs with restricted AllowedIPs
remain restricted: other destinations are unreachable, never routed on the host.

Hooks (PreUp/PostUp/PreDown/PostDown), Table, SaveConfig, FwMark, unknown or
repeated keys are explicitly rejected. No imported value is executed as a shell
command. Configs without addresses/DNS, DNS stub addresses and overlapping
operational policies needing wg-quick scripting need manual conversion.
Endpoint hostname resolution happens before moving the interface, using the host
resolver. It is separate from application DNS; endpoint IPs are not periodically
re-resolved in this MVP. Stop/start refreshes resolution.

## Lifecycle

Profiles persist across reboots; running namespaces do not. Start is manual.
Stopping first deletes `wg0`, then removes the named namespace. Existing apps
keep an isolated namespace with loopback only. Starting again creates a fresh
namespace; restart the disconnected apps to use it. This prevents reconnecting
old apps by accident. A service crash leaves existing namespaces/tunnels intact;
a systemd restart/stop kills service-owned app processes (`KillMode=control-group`)
but does not remove namespace handles. After a broker restart, status rediscovers
them. Stop profiles explicitly before service removal.

For uninstall, stop all your profiles, close apps, disable the service, and remove
the package. `/var/lib/appwire` retains private configs for deliberate manual
removal; package uninstall does not silently erase credentials. Empty runtime DNS
directories may remain until reboot, contain no keys, and are reused on restart.

## Tests and limits

- `make check`: parser, RPC/descriptor bounds, ownership, lifecycle failure paths,
  secret-free status, and launch validation.
- `./tests/integration.sh`: a disposable user + mount + network namespace with
  two locally generated WireGuard peers. Exercises real encrypted IPv4/IPv6,
  DNS, handshake/counters, capability removal, descriptor cleanup, and retained-app
  fail-closed behavior. No provider credentials or host routing changes.
- `tests/gui_smoke.py`: offscreen GTK rendering and interactions with a fake
  service response. Requires an available GTK display backend.

The isolated integration harness can map only its own user to namespace-root.
It skips supplementary-group changes in that harness only; production refuses
root clients and performs the real group/GID/UID drop. Full root-service operation,
real Proton exit IP and the Faugus/Wine chain require a post-install host acceptance
run. The project is an MVP, not an independently security-audited VPN product.
See [acceptance steps](docs/ACCEPTANCE.md) and [test results](docs/TEST-RESULTS.md).

References: [WireGuard namespace architecture](https://www.wireguard.com/netns/),
[Linux Unix sockets and peer credentials](https://man7.org/linux/man-pages/man7/unix.7.html),
[setns](https://man7.org/linux/man-pages/man2/setns.2.html).
