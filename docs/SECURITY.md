# Security boundary

AppWire prevents direct IP fallback from its app namespace to the host NIC.
The namespace has only loopback and WireGuard. No broad host routing/firewall
state is changed. Stop removes the WireGuard interface before deleting the name.
Apps holding the old namespace stay disconnected. Missing or broken profiles
cause launch failure, never an unisolated retry.

## Privileged surface

One root Python service, standard library only. Fixed root-owned entry point
uses Python isolated mode (`-I`) and a fixed module directory. Service environment
is reset, subprocess executables use absolute paths, and no shell is invoked.
Application PID inspection runs in the unprivileged client; the broker does not
need CAP_SYS_PTRACE. Kernel capabilities are bounded in the unit; CAP_SYS_ADMIN remains necessary for
namespace/mount entry. This is significant privilege, not equivalent to a
memory-safe, formally verified helper. The broker is the component to audit.

Socket is root:appwire 0660 in a root-owned directory. Kernel SO_PEERCRED supplies
UID. Membership is checked server-side; request UID/GID/path overrides are not
accepted. Every profile/config/namespace name is derived from that UID and a
validated short profile name. Users cannot access another user's profiles through
the API. Membership delegates network-namespace creation and own-user app launch,
not arbitrary root commands. An authorized user can consume resources; this is
not a hostile multi-tenant service. There are 32 profiles/user, 64 simultaneous
workers globally, 128 KiB RPC packets, 32 KiB configs, and bounded tool timeouts.
Idle request connections expire after five seconds.

Configuration is parsed without interpolation or shell execution. Private keys
are stored root-only and piped to wg, not passed in argv. Tool stderr is not sent
back because wg may include sensitive input. Status requests specific public
fields, never `wg show dump`. Config replacement is atomic and forbidden while
active. Operations share a lock so launch cannot race stop before namespace entry.

App launch accepts exactly stdin/stdout/stderr and a working-directory FD.
Socket stdio is rejected. Network namespace handles and all other broker FDs
close before exec. The child installs private read-only resolver/NSS bind mounts,
sets no-new-privileges, empties the capability bounding set, sets supplementary
groups/GID/UID to the authenticated account, explicitly clears capabilities, and
only then executes caller argv/environment. Caller environment is never used by
privileged network commands. LD_PRELOAD/PYTHONPATH therefore affect only the
already-unprivileged application. No setuid or passwordless sudo is installed.

The service uses the host mount namespace intentionally: /run/netns handles must
survive daemon restarts. Adding PrivateMounts/ProtectSystem casually can change
that behavior. Child applications unshare mounts independently. Service restart
kills its app cgroup; namespaces and secrets remain until explicit stop/removal.

## What this does not isolate

This is not a sandbox for malicious applications. Desktop compatibility retains
the user's files, Wayland/X11, session bus, audio sockets and other filesystem
Unix sockets. An app can ask a host-side proxy, portal, resolver API, existing
launcher or Wine server to make network requests on its behalf. The ordinary NSS
DNS path is corrected (`hosts: files dns`), but this is not a filter on explicit
IPC or D-Bus calls. A malicious app can also ask this same-user broker to launch
elsewhere if the user is entitled to do so. Root can always modify namespaces.

Applications that deliberately delegate networking outside their namespace
require a stronger application sandbox and restricted desktop IPC. Apps launched
inside AppWire must be fresh processes, particularly Wine/prefix servers and
single-instance launchers. Verify the actual game PID is listed in status.

This MVP does not periodically re-resolve endpoint hostnames, auto-start after
reboot, provide PTY job control, track all detached descendants as one app job,
or provide per-app cgroups. CLI disconnect terminates a still-running immediate
app process group; detached descendants may survive, always in their existing
network namespace. Normal GUI closure leaves its detached CLI/app running.
