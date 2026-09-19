PREFIX ?= /usr
DESTDIR ?=

.PHONY: check install
check:
	python -m unittest discover -s tests -v

install:
	install -d "$(DESTDIR)$(PREFIX)/lib/appwire/appwire"
	install -m 644 appwire/*.py "$(DESTDIR)$(PREFIX)/lib/appwire/appwire/"
	install -Dm755 bin/appwire "$(DESTDIR)$(PREFIX)/bin/appwire"
	install -Dm755 bin/appwired "$(DESTDIR)$(PREFIX)/lib/appwire/appwired"
	install -Dm644 packaging/appwire.service "$(DESTDIR)$(PREFIX)/lib/systemd/system/appwire.service"
	install -Dm644 packaging/appwire.sysusers "$(DESTDIR)$(PREFIX)/lib/sysusers.d/appwire.conf"
	install -Dm644 packaging/appwire.desktop "$(DESTDIR)$(PREFIX)/share/applications/appwire.desktop"
	install -Dm644 README.md "$(DESTDIR)$(PREFIX)/share/doc/appwire/README.md"
	install -d "$(DESTDIR)$(PREFIX)/share/doc/appwire/docs"
	install -m644 docs/*.md "$(DESTDIR)$(PREFIX)/share/doc/appwire/docs/"
	install -Dm644 LICENSE "$(DESTDIR)$(PREFIX)/share/licenses/appwire/LICENSE"
