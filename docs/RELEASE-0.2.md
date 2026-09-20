# AppWire 0.2: usability and recovery

This release keeps the original privileged architecture. The broker gains only
profile rename, explicit replacement, version/host-namespace information,
per-profile error isolation and namespace generation identifiers. Preferences,
launch-session bookkeeping, browser templates, log viewing and measurements run
as the desktop user. It is still a custom application, not an official Proton or
Faugus component.

## Installation and upgrades

Build with `makepkg -f`. Close AppWire-launched applications before upgrading.
The package never automatically restarts the broker: restarting it terminates
applications in its service cgroup. After installing, restart the service only
when those apps have exited, then reopen the GUI. `appwire doctor` reports client
and broker versions so an old running broker is not mistaken for new code.

For first setup, run `appwire setup` **as your normal user**. It uses sudo only
for three fixed system commands: create the packaged group, enroll your account,
and enable/start the service. It does not restart an active service or start VPN
profiles. Log out of the desktop and back in after new group enrollment. The GUI
Setup button can open this command in an installed terminal.

The root-owned configs in `/var/lib/appwire` remain intact. The GUI retries a
missing broker, explains permission failures, and distinguishes unavailable
profiles from an empty collection. A cold-boot acceptance test must still be
performed on the installed release; the automated setup test verifies enablement
commands without rebooting the developer's machine.

## Profile management

Import selects multiple files. Each suggested name can be edited, and replacements
require confirmation. CLI alternatives:

```sh
appwire import-many ~/Downloads/proton-us-*.conf
appwire import proton-us-ca-245 ~/Downloads/replacement.conf --replace
appwire rename old-name new-name
appwire remove old-name
```

Active profiles cannot be replaced, renamed or removed. Provider revocation does
not remove local profiles. A failed handshake is not sufficient evidence of key
revocation. Both interfaces update saved app references when renaming a profile. The GUI
also supports a friendly display name and notes while retaining a stable ID.

Status separates interface readiness, handshake age, transfer counts and a dated
exit check. IPv4 and IPv6 checks are separate. Probe results are associated with
a profile and tunnel generation and invalidated after a detected restart/stop.
Only an explicit probe claims verified Internet access.

## Launches and sessions

Save an app's name, executable/arguments, working directory and chosen profile.
The GUI can create a desktop shortcut for that saved entry. Launching starts the
selected tunnel first; a failed start never triggers a Direct fallback.
Direct is an explicit separate choice for intentional host networking.

```sh
appwire run --start proton-us-ny-447 -- faugus-launcher
appwire save-app --cwd "$HOME" Battle.net proton-us-ny-447 -- faugus-launcher
appwire launch Battle.net
appwire desktop-shortcut Battle.net
appwire sessions
```

Close an existing Wine/Battle.net chain before switching its network. The GUI
warns when likely shared processes exist; it cannot guarantee that arbitrary
applications will not delegate through desktop IPC. The browser template uses
a dedicated Firefox/Chromium data directory for the selected profile to reduce
single-instance reuse.

Session bookkeeping is advisory, user-owned and grouped by namespace, including
helpers. It can show a retained disconnected namespace after stopping a profile.
Close-session sends SIGTERM to currently matching owned processes using pidfds;
it does not force-kill them. Wait for them to exit before relaunching. AppWire
cannot move an already-running process into the new tunnel. Applications launched
before this release may appear only in live profile status. Records are pruned
on reboot or when no recorded process identity remains; this is not a durable
process supervisor. A namespace session groups multiple launches in that same
tunnel, so closing it closes the whole group.

## Diagnostics, logs and measurements

`appwire doctor` is read-only and describes the environment it can observe. It
checks group/session membership, service enablement/activity, tools, runtime
files and broker version/access. It does not claim to prove a handshake, DNS
isolation or live Internet access. The GUI exports only the diagnostic preview,
not WireGuard configs, environment variables or application logs.

GUI application logs are private and continuously rotated between two files of
at most 2 MiB each. A client-side pipe relay drains application output; no root
logging helper is added. The log viewer reads only the last 64 KiB. Application output can contain sensitive data.

```sh
appwire measure proton-us-ny-447 --seconds 300 --notes 'Same character and area'
appwire measure --direct direct --seconds 300 --notes 'Normal launcher, no VPN'
appwire history
```

Measurements inspect actual process-attributed WowB.exe TCP/3724 sockets, not
Proton datacenter ping. They retain sampled smoothed RTT, retransmission deltas,
traffic-counter deltas, endpoint, namespace, tunnel status/exit (when the probe
succeeds), time and notes. The GUI can mark perceived stalls while recording.
Direct requires broker-confirmed host namespace identity and a game process in
that namespace; there is no root measurement command or silent fallback.

Profiles must already be running for measurements. Repeated comparisons require
explicit game relaunches. Keep gameplay conditions similar and compare matching
endpoints. Idle sockets may retain old RTT estimates; use traffic deltas to
interpret them. Neither these RTT percentiles nor retransmission counts measure
input-to-castbar latency or packet-loss percentage. No automatic winner or live
route switch is applied.

## Backlog disposition and limits

- AW-01–09: setup/recovery, status/error handling, asynchronous controls and
  profile management implemented. Installed cold-boot behavior still needs host
  acceptance. Operation errors have safe stage codes; deep provider diagnosis is
  intentionally not inferred from a generic timeout.
- AW-10–14: independent profile/app settings, saved launches, desktop shortcuts,
  namespace sessions and maintenance warnings implemented. Friendly profile
  aliases and notes are separate from IDs. Session grouping is by namespace rather
  than a full launch tree. Service-cgroup ownership remains unchanged.
- AW-15–18: doctor/export, game socket measurement, history, stall markers and
  log viewer and continuously bounded GUI launch logs implemented.
- AW-19–21: package setup messages, version checks, regression tests and this
  updated evidence record included. Real root-service cross-user acceptance and
  an installed reboot are not substitutes for isolated tests and remain manual.
- AW-22: optional dedicated browser template implemented.
- AW-23: provider-specific P2P port-forwarding remains a separate optional
  project; no NAT-PMP lease manager or torrent-client integration is claimed.

No change to host routing, NetworkManager or provider credentials is needed to
build or test this release. Uninstall deliberately retains configs and local
preferences until the user chooses to remove them.
