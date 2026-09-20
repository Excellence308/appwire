# AppWire 0.1

Per-application WireGuard routing for Arch Linux using Linux network namespaces.

AppWire lets you start selected applications inside an isolated WireGuard network namespace while leaving the host and other applications on their normal connection. It provides a GTK3 GUI, a CLI, and a small privileged system service that owns networking operations.

AppWire is an independent project. It is not an official WireGuard, Proton VPN, Faugus, or Arch Linux component.

## Status

`0.1.0` is the first public-ready release. The core namespace, WireGuard, DNS, process reporting, CLI, GUI, packaging, and test paths are implemented. AppWire has not undergone an independent security audit, and it should not be treated as a sandbox for hostile applications.

## Architecture

```text
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

The design does not require NetworkManager, veth pairs, forwarding, NAT, host firewall edits, host default-route changes, setuid executables, sudoers rules, downloaded runners, or shell hooks.

WireGuard's encrypted socket uses the existing host uplink. Cleartext application traffic sees only `lo` and `wg0`. A stopped or unreachable tunnel provides no alternative host NIC. IPv6 is tunneled when configured; otherwise the namespace has no external IPv6 route.

This is traffic isolation for cooperative applications, not a malicious-application sandbox. See [Security](docs/SECURITY.md).

## Requirements

AppWire currently targets Arch Linux and requires:

- Python
- PyGObject
- GTK3
- iproute2
- wireguard-tools
- systemd
- curl

The Arch package declares these dependencies.

## Install on Arch Linux

Clone the repository and build the tagged release through the included `PKGBUILD`:

```sh
git clone https://github.com/Excellence308/appwire.git
cd appwire
git checkout v0.1.0
makepkg -si
```

Then enable AppWire for your user:

```sh
sudo systemd-sysusers
sudo usermod -aG appwire "$USER"
sudo systemctl enable --now appwire.service
```

Log out and back in after the first group enrollment so graphical launchers inherit the new group membership.

Do not run the GUI or CLI with `sudo`.

For development and packaging details, see [Packaging and releases](docs/PACKAGING.md).

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

`start` means the interface and routes are configured; it does not claim that the remote VPN peer has answered. `status` separately reports handshake state, transfer counters, namespace identity, and processes running in the namespace.

`probe` makes a fresh HTTPS request inside the tunnel and prints the observed IPv4 address. `probe --ipv6` tests IPv6. A failed probe is an error; AppWire does not silently retry on the host connection or return a cached success.

Application launch is explicit and fail-closed. `appwire run` refuses to start a command if the selected profile is stopped, incomplete, or has an unexpected network interface. The CLI preserves arguments, environment, working directory, and standard streams, and propagates the launched process's exit status.

## GUI

Run:

```sh
appwire gui
```

The GTK GUI can import profiles, start and stop tunnels, refresh handshake/transfer/process status, check the current exit IPv4 address, and launch a command without shell expansion.

Application output is written to `$XDG_STATE_HOME/appwire/applications.log`, or `~/.local/state/appwire/applications.log` when `XDG_STATE_HOME` is unset.

Closing the GUI does not terminate applications that were already launched through AppWire.

## Faugus / Wine / Battle.net

For a launcher chain such as Faugus → Battle.net → WoW:

1. Fully quit existing Faugus, Battle.net, Wine, and game processes using the intended prefix.
2. Start the AppWire profile.
3. Launch the complete chain through AppWire:

   ```sh
   appwire run proton-us -- faugus-launcher
   ```

4. Launch Battle.net and the game normally from that Faugus instance.
5. Confirm the relevant game process appears in:

   ```sh
   appwire status proton-us
   ```

Existing Wine servers and single-instance launchers can hand work to a process that was already running outside the namespace, so the presence of a launcher window alone is not proof of isolation. Verify the actual application or game PID.

Wayland/X11, audio, and the normal desktop session environment remain available. AppWire does not modify Wine prefixes, Faugus settings, or existing VPN managers.

Do not use the same WireGuard provider key simultaneously in multiple VPN managers. WireGuard peer roaming can cause the sessions to disrupt each other.

## Supported WireGuard configuration

AppWire accepts ordinary provider-style wg-quick files containing one `[Interface]` section and up to 16 `[Peer]` sections.

Supported interface fields include:

- `PrivateKey`
- `Address`
- `DNS`
- `MTU`
- `ListenPort`

Supported peer fields include:

- `PublicKey`
- `PresharedKey`
- `Endpoint`
- `AllowedIPs`
- `PersistentKeepalive`

IPv4 and IPv6 addresses and endpoints are supported. Numeric DNS servers are required and must be covered by `AllowedIPs`; search domains may accompany them.

AppWire deliberately rejects configuration directives that would require executing arbitrary shell commands or reproducing complex wg-quick policy behavior, including hooks such as `PreUp`, `PostUp`, `PreDown`, and `PostDown`, as well as `Table`, `SaveConfig`, `FwMark`, unknown keys, and repeated unsupported keys.

No imported configuration value is executed as a shell command.

Endpoint hostnames are resolved before the WireGuard interface is moved into its network namespace. Restarting a profile refreshes endpoint resolution.

## Security model

The GUI and CLI run as the invoking user. The privileged broker is limited to a defined local RPC interface and authenticates callers using Unix-socket peer credentials.

Imported WireGuard profiles are stored under:

```text
/var/lib/appwire/<UID>/
```

with root-only access. Private keys are not passed on command lines and are not exposed through normal status responses.

Before launching an application, AppWire enters the selected network namespace, creates private DNS mounts, drops supplementary groups, UID/GID privileges, and capabilities, and then executes the requested application.

For assumptions, boundaries, and non-goals, read [docs/SECURITY.md](docs/SECURITY.md).

## Lifecycle

Profiles persist across reboots. Running network namespaces do not need to be automatically started at boot; profiles are started explicitly.

Stopping a profile deletes `wg0` first and then removes the named namespace. Applications still holding the old namespace remain isolated with loopback only. Starting the profile again creates a fresh namespace, so disconnected applications must be restarted deliberately.

A broker restart can rediscover existing named namespaces. Stop profiles explicitly before uninstalling AppWire.

Package removal deliberately does not erase `/var/lib/appwire`, because that directory may contain private VPN configuration. Remove retained profiles manually if you no longer want them.

## Testing

Run the unit suite:

```sh
make check
```

Run the integration harness:

```sh
./tests/integration.sh
```

Validate desktop metadata:

```sh
desktop-file-validate packaging/appwire.desktop
```

The integration harness creates disposable local network and mount namespaces and locally generated WireGuard peers. It exercises encrypted IPv4/IPv6 traffic, DNS behavior, handshakes/counters, capability removal, descriptor cleanup, and fail-closed behavior without using provider credentials or changing host routes.

For manual post-install verification, see [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md). Recorded test information is in [docs/TEST-RESULTS.md](docs/TEST-RESULTS.md).

## Packaging

The repository contains an Arch `PKGBUILD`, service unit, sysusers configuration, and desktop entry. The package recipe is release-oriented and resolves the corresponding `v${pkgver}` Git tag.

Before a future AUR publication, the AUR package should be maintained in its own AUR Git repository using the immutable release tarball and its SHA-256 checksum, with `.SRCINFO` generated from the final recipe. The full workflow is documented in [docs/PACKAGING.md](docs/PACKAGING.md).

## License

AppWire is released under the MIT License. See [LICENSE](LICENSE).

## References

- [WireGuard network namespace architecture](https://www.wireguard.com/netns/)
- [Linux Unix sockets and peer credentials](https://man7.org/linux/man-pages/man7/unix.7.html)
- [setns(2)](https://man7.org/linux/man-pages/man2/setns.2.html)
