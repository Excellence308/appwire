# Packaging and releases

AppWire uses semantic upstream versions (`0.1.0`, `0.2.0`, …) and Arch package revisions (`pkgrel`) independently.

## Upstream release

A release tag is named `v${pkgver}` and must point at the exact commit intended for release. Before tagging:

```sh
make check
desktop-file-validate packaging/appwire.desktop
makepkg --syncdeps --cleanbuild
namcap PKGBUILD
namcap appwire-*.pkg.tar.zst
```

The release source of truth is the Git tag. Do not move a published tag after external users or package repositories depend on it. During pre-publication bring-up, retagging is acceptable while the release has not been announced or consumed downstream.

## Arch package in this repository

The root `PKGBUILD` is a developer/upstream packaging recipe. It builds the source tree that contains it and performs no network fetches. This makes local development, release validation and installation deterministic even when the repository is private or unavailable.

The GUI is part of the normal AppWire package, so GTK dependencies are mandatory rather than optional. The package check validates both the Python test suite and the desktop entry.

Because the root recipe builds the checked-out tree, users installing directly from source should first check out the desired release tag:

```sh
git checkout v0.1.0
makepkg --syncdeps --cleanbuild --install
```

## Future AUR publication

The AUR package should live in its own AUR Git repository and contain only the packaging files required by AUR, normally:

- `PKGBUILD`
- `.SRCINFO`

For an AUR submission, use the immutable GitHub release/archive tarball and pin its checksum. Example shape:

```sh
pkgname=appwire
pkgver=0.1.0
pkgrel=1
pkgdesc='Per-application WireGuard network namespace manager'
arch=('any')
url='https://github.com/Excellence308/appwire'
license=('MIT')
depends=('python' 'python-gobject' 'gtk3' 'iproute2' 'wireguard-tools' 'systemd' 'curl')
checkdepends=('desktop-file-utils')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('REPLACE_WITH_RELEASE_ARCHIVE_SHA256')

check() {
    cd "$srcdir/$pkgname-$pkgver"
    make check
    desktop-file-validate packaging/appwire.desktop
}

package() {
    cd "$srcdir/$pkgname-$pkgver"
    make DESTDIR="$pkgdir" PREFIX=/usr install
}
```

Generate the checksum only after the release tag is final:

```sh
curl -L -o "appwire-$pkgver.tar.gz" \
  "https://github.com/Excellence308/appwire/archive/refs/tags/v$pkgver.tar.gz"
sha256sum "appwire-$pkgver.tar.gz"
```

Then generate `.SRCINFO` from the final AUR `PKGBUILD`:

```sh
makepkg --printsrcinfo > .SRCINFO
```

Run `namcap` on both the recipe and built package before submitting. Keep `.SRCINFO` synchronized with every metadata change.
