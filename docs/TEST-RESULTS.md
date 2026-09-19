# MVP validation — 19 September 2026

## Passed

- 20 automated unit tests: config validation and hook rejection, per-user profile
  paths/permissions, group authorization, unknown RPC field rejection, packet/FD
  handling, rollback, stop ordering, unexpected-interface refusal, socket-stdio
  refusal and status secret exclusion.
- 20 isolated kernel integration checks using real, locally generated WireGuard
  peers: handshake, counters, IPv4/IPv6 traffic, private DNS/NSS, DNS source address,
  zero app capabilities, no-new-privileges, no inherited privileged/socket FDs,
  working-directory preservation, peer outage, stop/restart behavior for a live
  process, namespace cleanup and unchanged birthplace routing.
- Real GTK3 offscreen widget test: profile selection, asynchronous status and
  exit-IP actions, text content and rendering. The supplied preview uses
  synthetic documentation addresses and a sample game PID, not a live VPN.
- CLI help and Python compilation.
- Arch makepkg build, including its check() phase and package metadata generation.
- Desktop entry validation.
- systemd unit validation with ExecStart redirected to the staged package
  executable, because the package is not installed on the host.

## Environment

Linux 7.2.6-zen2-1-zen; Python 3.14.7; iproute2 7.2.0;
wireguard-tools 1.0.20260223; GTK 3.24.52.

The integration harness runs inside disposable user/mount/network namespaces.
Its outer namespace is the simulated 'host'; it has no physical NIC. Network
permission was granted so tests could use netlink and the kernel WireGuard
implementation. No production routes, existing VPNs or Faugus settings were
changed. Peer-outage simulation changes only the local test peer's UDP port.

A real mount-remount failure found during testing was fixed by retaining inherited
mount restrictions when making DNS bind mounts read-only. The test harness also
separates outage simulation from interface/address deletion so its own fixture
changes are not mistaken for changes made by AppWire.

## Not yet verified

- Installing/enabling the root system service on the user's host.
- Real supplementary-group/GID/UID drop through that installed service. The
  single-UID integration mapping cannot exercise multiple identities; it replaces
  only the group update and account lookup in its harness. Production code does
  not contain that bypass and rejects UID 0 clients. Capability removal and
  namespace/DNS entry were exercised for real.
- Live Proton exit IP, external DNS/IPv6 behavior and real provider outage.
- Faugus, Wine, Battle.net and WoW through this new service.
- Root-service cross-user acceptance, reboot/restart acceptance, and independent
  security review. Unit-level authorization/ownership checks passed.

These are documented in ACCEPTANCE.md. The successful isolated suite is not a
claim that production VPN or gaming behavior has already been validated.
