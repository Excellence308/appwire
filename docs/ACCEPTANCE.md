# Post-install host acceptance

The isolated suite is useful evidence, but does not replace these checks against
the installed root service. Keep the working vpnns setup available until passed.

1. Quit apps using the existing provider key, then stop that old VPN profile.
   Do not interrupt an active game without saving/quitting first.
2. Build/install the package following README, enroll the intended user in
   appwire, and log in again. Verify root CLI launches are rejected.
3. Import a disposable provider config owned by the user. Verify its stored copy
   is root-owned 0600 under /var/lib/appwire/UID. Never print or log its keys.
4. Capture host IPv4/IPv6 routes and host exit IP. Start the profile, check
   `appwire status PROFILE`, then `appwire probe PROFILE`. Confirm a provider exit
   and fresh handshake. The host routes and exit must be unchanged.
5. Run `appwire run PROFILE -- id` and inspect the launched process's
   /proc/self/status. UID/GID/groups must be the user, CapEff/CapPrm/CapBnd zero,
   and NoNewPrivs 1. Attempted sudo/setuid elevation must fail.
6. Check DNS with `appwire run PROFILE -- getent ahostsv4 battle.net` and inspect
   /etc/resolv.conf and the hosts line in /etc/nsswitch.conf inside the launched
   process. Confirm the profile resolver and `hosts: files dns`.
7. Launch Faugus, Battle.net and the game. Confirm the actual game PID appears in
   AppWire's application list. Compare namespace inode if desired. Verify Wayland,
   audio, rendering, controller input and normal game exit.
8. Using a disposable long-running curl loop instead of the game, stop the
   profile. Further network requests must fail for both IPv4 and IPv6. Start the
   profile again: the old app must stay disconnected; a freshly launched app must
   work. Failure to reach the VPN endpoint must never reveal the host exit IP.
9. Verify a second local account cannot status/start/run your profile, and a user
   outside appwire cannot connect to the broker. Pass malformed configs/unknown
   request fields: they must fail without creating a host route or executing hooks.
10. Test service restart with disposable apps: app processes terminate as
    documented, namespaces remain discoverable, and explicit stop removes them.
    Reboot: profiles remain stored; status is stopped until explicitly started.

Record outcomes and versions. Do not infer provider connectivity from 'up', or
Wine isolation merely from a visible launcher window.
