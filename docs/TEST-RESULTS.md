# Validation update — 20 September 2026, AppWire 0.2.0

- 45 unit tests pass, including profile conflicts/rename, per-profile failures,
  connection recovery, session identity/PID reuse, fail-closed launch selection,
  setup enablement, bounded logging, shortcut escaping and TCP counter handling.
- 21 disposable-kernel WireGuard checks pass: IPv4/IPv6 traffic, DNS, credential
  and descriptor isolation, peer outage, and retained-app stop/restart behavior.
- GTK smoke and regression scripts pass against a fake service: initial service
  failure and recovery, stale exit invalidation, profile changes, unavailable
  states, disabled controls and visible busy feedback. Screenshot inspected.
- A ten-second disposable-network TCP fixture passes the real sampler: synthetic
  WowB.exe process attribution, namespace verification, ten samples, traffic
  deltas and structured output without raw socket dumps.
- Arch package build succeeds with its unit-test phase. Desktop entry validation,
  Python compilation, shell syntax and git whitespace checks pass.

These tests do not install or restart the production service. Full installed
0.2 root-service cross-user acceptance, a real reboot and the updated Faugus/WoW
GUI workflow remain to be tested after installation. No fresh provider latency
ranking was produced.

The earlier host trial's disconnect report records successful provider exit,
unchanged host IPv4/IPv6 routes, blocked retained-app traffic after stop/restart,
and WoW/Wine processes remaining in the old disconnected namespace. Those are
historical 0.1 host results, not evidence that 0.2 has been deployed.

Commands for additional checks:

```sh
make check
python tests/gui_smoke.py /tmp/appwire-gui.png
python tests/gui_regression.py
./tests/integration.sh
APPWIRE_MEASUREMENT_TEST=1 unshare --user --map-root-user --net python tests/measurement_integration.py
```

## Archived MVP validation (19 September 2026)

The following is the original milestone record. Its "not yet verified" section
reflects that earlier point in time and is superseded by the update above.

# MVP validation — 19 September 2026

## Passed

- 22 automated unit tests: config validation and hook rejection, per-user profile
  paths/permissions, group authorization, unknown RPC field rejection, packet/FD
  handling, rollback, stop ordering, unexpected-interface refusal, socket-stdio
  refusal and status secret exclusion.
- 21 isolated kernel integration checks using real, locally generated WireGuard
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

- Full installed-service acceptance beyond the initial successful import/start
  and credential/capability assertions. The host service is installed and running;
  boot enablement has deliberately not been requested.
- Live Proton exit IP, external DNS/IPv6 behavior and real provider outage.
- Faugus, Wine, Battle.net and WoW through this new service.
- Root-service cross-user acceptance, reboot/restart acceptance, and independent
  security review. Unit-level authorization/ownership checks passed.

These are documented in ACCEPTANCE.md. The successful isolated suite is not a
claim that production VPN or gaming behavior has already been validated.

## Host trial follow-up — package release 2

The installed service successfully imported and started the Proton profile, and
launched a process with the expected UID/GID/groups, zero capabilities and
NoNewPrivs. The trial then exposed a protected `/run/netns` directory: the
unprivileged check could not stat the namespace handle. The same assumption
also affected the client's application listing.

Release 2 returns the namespace inode through the authenticated status response.
Clients inspect only their own process namespaces; directory permissions and
broker capabilities remain unchanged. Added regression coverage forbids client
access to `/run/netns` and checks that the reported identity matches a real
launched process. The trial can resume an already-running profile while retaining
its original host baseline. A live provider handshake/exit and gaming trial remain
unverified at the point of this correction.
