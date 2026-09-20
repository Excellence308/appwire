# Maintainer: Excellence308 <180781538+Excellence308@users.noreply.github.com>

pkgname=appwire
pkgver=0.1.0
pkgrel=1
pkgdesc='Per-application WireGuard network namespace manager'
arch=('any')
url='https://github.com/Excellence308/appwire'
license=('MIT')
depends=(
    'python'
    'python-gobject'
    'gtk3'
    'iproute2'
    'wireguard-tools'
    'systemd'
    'curl'
)
checkdepends=('desktop-file-utils')
source=()
sha256sums=()

check() {
    cd "$startdir"
    make check
    desktop-file-validate packaging/appwire.desktop
}

package() {
    cd "$startdir"
    make DESTDIR="$pkgdir" PREFIX=/usr install
}
