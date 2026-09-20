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
makedepends=('git')
checkdepends=('desktop-file-utils')
source=("git+https://github.com/Excellence308/appwire.git#tag=v${pkgver}")
sha256sums=('SKIP')

check() {
    cd "$srcdir/$pkgname"
    make check
    desktop-file-validate packaging/appwire.desktop
}

package() {
    cd "$srcdir/$pkgname"
    make DESTDIR="$pkgdir" PREFIX=/usr install
}
