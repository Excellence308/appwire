# Contributing to AppWire

AppWire is an early-stage Linux networking project with a privileged broker, so changes that affect namespace handling, privilege dropping, configuration parsing, or process launch should be treated as security-sensitive.

## Development setup

AppWire currently targets Arch Linux. Install the runtime and development dependencies:

```sh
sudo pacman -S --needed base-devel git python python-gobject gtk3 iproute2 wireguard-tools systemd curl desktop-file-utils namcap
```

Clone the repository:

```sh
git clone https://github.com/Excellence308/appwire.git
cd appwire
```

Run the unit tests:

```sh
make check
```

Validate the desktop entry:

```sh
desktop-file-validate packaging/appwire.desktop
```

The integration harness exercises real Linux namespaces and locally generated WireGuard peers:

```sh
./tests/integration.sh
```

Read the script before running it on an unfamiliar system. It is designed not to use provider credentials or modify the host default route.

## Packaging checks

For release/package changes:

```sh
makepkg --syncdeps --cleanbuild
namcap PKGBUILD
namcap appwire-*.pkg.tar.zst
```

See [docs/PACKAGING.md](docs/PACKAGING.md) for the release and future AUR workflow.

## Branches

- `main` is the stable line.
- `experimental` may contain larger or unfinished changes and is not the release source of truth.

Create focused branches from `main` for normal fixes and features.

## Security-sensitive changes

Please include tests when changing any of the following:

- Unix-socket authorization or peer credentials
- profile ownership or permissions
- WireGuard configuration parsing
- network namespace creation or entry
- DNS mount handling
- UID/GID/group or capability dropping
- process launch and file-descriptor handling
- fail-closed routing behavior

Do not add shell evaluation of imported configuration values. Avoid exposing private or preshared WireGuard keys through logs, status APIs, process arguments, or error messages.

For the current trust model and known limitations, see [docs/SECURITY.md](docs/SECURITY.md).

## Pull requests

Before submitting a change:

1. Rebase or merge the current `main` as appropriate.
2. Run the unit tests.
3. Run relevant integration tests for networking/security changes.
4. Validate desktop metadata for GUI/packaging changes.
5. Keep unrelated formatting or refactoring out of focused fixes where possible.
6. Explain user-visible behavior changes and security implications in the pull request.

By contributing, you agree that your contribution may be distributed under the project's MIT License.
