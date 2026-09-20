"""Offscreen GTK smoke test with fake service data, never a production profile."""
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['GSETTINGS_BACKEND'] = 'memory'
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
Gtk.Window = Gtk.OffscreenWindow
from appwire.gui import Window

status = {'profile': 'proton-us-ca-245', 'generation': 'fixture', 'state': 'up', 'peers': [{'endpoint': '192.0.2.1:51820', 'handshake_age': 14, 'received': 184549376, 'sent': 4194304}], 'applications': [{'pid': 1234, 'name': 'example-app'}]}
def call(op, **kwargs):
    return {'profiles': [status]} if op == 'list' else dict(status)


def pump(duration):
    end = time.monotonic() + duration
    while time.monotonic() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(.01)

with patch('appwire.gui.client.call', side_effect=call), patch('appwire.gui.client.probe', return_value='203.0.113.15'):
    window = Window()
    window.show_all()
    pump(.3)
    assert window.selected() == status['profile']
    assert '176.00 MiB' in window.fields['Transfer'].get_text()
    assert '14 seconds ago' in window.fields['Handshake'].get_text()
    assert 'example-app' in window.apps.get_text()
    window.probe()
    pump(.2)
    assert '203.0.113.15' in window.fields['Exit IP'].get_text()
    output = Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/appwire-gui.png')
    image = window.get_pixbuf()
    assert image is not None
    image.savev(str(output), 'png', [], [])
    window.destroy()
    print('PASS: profile, status, IP check and compact GTK rendering')
    print(output)
