# Local-source package: run makepkg from this project directory.
pkgname=appwire
pkgver=0.1.0
pkgrel=1
pkgdesc='Small per-application WireGuard namespace manager'
arch=('any')
license=('MIT')
depends=('python' 'iproute2' 'wireguard-tools' 'systemd' 'curl')
optdepends=('python-gobject: GTK GUI' 'gtk3: GTK GUI')
makedepends=('make')
source=()
sha256sums=()

check() {
    cd "$startdir"
    make check
}

package() {
    cd "$startdir"
    make DESTDIR="$pkgdir" install
}
