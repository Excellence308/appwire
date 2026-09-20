"""Exercise state-aware controls and passive polling with real GTK widgets."""
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['GSETTINGS_BACKEND'] = 'memory'
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
Gtk.Window = Gtk.OffscreenWindow
from appwire.gui import Window


def pump(seconds=.15):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(.005)


def status(name='test', generation='one', state='up'):
    return {'profile': name, 'generation': generation, 'state': state, 'peers': [], 'applications': []}


profiles = [status(), status('other')]
unavailable = True
gate = None
calls = []
def call(op, **values):
    calls.append(op)
    if unavailable:
        raise RuntimeError('Service unavailable; saved profiles remain intact')
    if op == 'list':
        return {'profiles': [dict(p) for p in profiles]}
    value = next(p for p in profiles if p['profile'] == values['profile'])
    if op == 'stop':
        value['state'] = 'stopped'
    elif op == 'start':
        value['state'] = 'up'
    snapshot = dict(value)
    if op == 'status' and gate is not None:
        gate.wait(5)
    return snapshot


with patch('appwire.gui.client.call', side_effect=call), patch('appwire.gui.client.probe', return_value='203.0.113.1'):
    window = Window()
    window.show_all()
    pump()
    assert 'unavailable' in window.message.get_text()
    assert not window.buttons['Start'].get_sensitive()
    assert not window.buttons['Stop'].get_sensitive()
    unavailable = False
    window.tick()
    pump()
    assert window.selected() == 'test'
    assert not window.buttons['Start'].get_sensitive()
    assert window.buttons['Stop'].get_sensitive()
    assert not window.buttons['Rename'].get_sensitive()
    assert set(window.buttons) == {'Import', 'Rename', 'Delete', 'Start', 'Stop', 'Refresh', 'Check IP', 'Launch'}
    assert not any('…' in button.get_label() or '...' in button.get_label() for button in window.buttons.values())
    for removed in ('saved', 'direct', 'measure', 'show_sessions', 'browser_template', 'setup', 'profile_notes'):
        assert not hasattr(window, removed), removed
    window.probe()
    pump()
    assert '203.0.113.1' in window.fields['Exit IP'].get_text()
    window.profiles.set_active(1)
    assert '203.0.113.1' not in window.fields['Exit IP'].get_text()
    window.profiles.set_active(0)
    # An unchanged passive update must emit no model, field or sensitivity changes.
    events = []
    model = window.profiles.get_model()
    model.connect('row-deleted', lambda *_: events.append('model'))
    window.profiles.connect('changed', lambda *_: events.append('selection'))
    for widget in window.buttons.values():
        widget.connect('notify::sensitive', lambda *_: events.append('sensitivity'))
    for widget in window.fields.values():
        widget.connect('notify::label', lambda *_: events.append('label'))
    gate = threading.Event()
    window.tick()
    pump(.03)
    assert window.polling
    assert window.buttons['Stop'].get_sensitive()
    assert window.profiles.get_sensitive()
    gate.set()
    pump()
    gate = None
    assert not events, events
    assert calls[-1] == 'status', 'polling must not reload the whole profile list'
    assert window.profiles.get_model() == model
    # An older in-flight response must not undo a stop action.
    gate = threading.Event()
    window.tick()
    pump(.03)
    window.action('stop')
    pump()
    assert window.buttons['Start'].get_sensitive()
    assert not window.buttons['Stop'].get_sensitive()
    gate.set()
    pump()
    gate = None
    assert window.statuses['test']['state'] == 'stopped'
    assert window.buttons['Rename'].get_sensitive()
    assert window.buttons['Delete'].get_sensitive()
    assert not window.buttons['Check IP'].get_sensitive()
    assert not window.buttons['Launch'].get_sensitive()
    before = len(calls)
    window.tick()
    pump()
    assert len(calls) == before, 'stopped profiles must not be polled'
    window.action('start')
    pump()
    window.command.set_text('example-app')
    assert window.buttons['Launch'].get_sensitive()
    window.probe()
    pump()
    profiles[0]['generation'] = 'new'
    window.tick()
    pump()
    assert not window.exit_results
    unavailable = True
    window.refresh()
    pump()
    assert not window.available and not window.buttons['Stop'].get_sensitive()
    window.destroy()
    print('PASS: minimal controls, start/stop gating, unchanged poll produces no UI notifications, no stopped polling, stale-response rejection, IP invalidation and service recovery')
