"""Offscreen real GTK widget smoke test; service is stubbed, no host mutations."""
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

# Substitute only the window container; all application widgets are real GTK.
Gtk.Window = Gtk.OffscreenWindow
from appwire.gui import Window

status = {'profile': 'proton-us', 'namespace': 'aw-1000-proton-us', 'state': 'up', 'peers': [{'endpoint': '192.0.2.1:51820', 'handshake_age': 14, 'received': 184549376, 'sent': 4194304}], 'applications': [{'pid': 1234, 'name': 'WowB.exe'}]}
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
    pump(.8)
    assert window.selected() == 'proton-us'
    window.action('status')
    pump(.3)
    buf = window.details.get_buffer()
    text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
    assert 'WowB.exe' in text and '176.00 MiB' in text and '14 seconds ago' in text, text
    window.probe()
    pump(.3)
    assert '203.0.113.15' in window.message.get_text()
    output = Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/appwire-gui.png')
    image = window.get_pixbuf()
    assert image is not None
    image.savev(str(output), 'png', [], [])
    print('PASS: GTK profile selection, status, async exit-IP probe and offscreen rendering')
    print(output)
