"""Small GTK profile manager. Background status updates never rebuild the window."""
from pathlib import Path
import datetime
import shlex
import subprocess
import threading
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from . import client, local
from .cli import read_config


class Window(Gtk.Window):
    def __init__(self):
        super().__init__(title='AppWire')
        self.set_default_size(620, 410)
        self.connect('destroy', self.close)
        self.closed = False
        self.busy = False
        self.polling = False
        self.modal_depth = 0
        self.revision = 0
        self.available = False
        self.updating = False
        self.names = []
        self.statuses = {}
        self.exit_results = {}
        self.buttons = {}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin=20)
        self.add(box)
        row = Gtk.Box(spacing=6)
        box.pack_start(row, False, False, 0)
        self.profiles = Gtk.ComboBoxText()
        row.pack_start(self.profiles, True, True, 0)
        self.button(row, 'Import', self.import_config)
        self.button(row, 'Rename', self.rename)
        self.button(row, 'Delete', self.remove)
        row = Gtk.Box(spacing=6)
        box.pack_start(row, False, False, 0)
        self.button(row, 'Start', lambda *_: self.action('start'))
        self.button(row, 'Stop', self.stop)
        self.state = Gtk.Label(xalign=0, margin_start=8)
        row.pack_start(self.state, True, True, 0)
        self.button(row, 'Refresh', lambda *_: self.refresh())
        grid = Gtk.Grid(column_spacing=20, row_spacing=10)
        box.pack_start(grid, False, False, 0)
        self.fields = {}
        for index, title in enumerate(('Server', 'Handshake', 'Transfer', 'Exit IP')):
            heading = Gtk.Label(label=title, xalign=0)
            heading.get_style_context().add_class('dim-label')
            grid.attach(heading, 0, index, 1, 1)
            value = Gtk.Label(label='—', xalign=0, selectable=True, hexpand=True)
            grid.attach(value, 1, index, 1, 1)
            self.fields[title] = value
        self.button(grid, 'Check IP', self.probe, grid_position=(2, 3))
        self.apps_expander = Gtk.Expander(label='Applications')
        self.apps = Gtk.Label(xalign=0, selectable=True)
        self.apps_expander.add(self.apps)
        box.pack_start(self.apps_expander, True, True, 0)
        row = Gtk.Box(spacing=6)
        self.command = Gtk.Entry(placeholder_text='Application command')
        self.command.connect('changed', lambda *_: self.sensitivities())
        self.command.connect('activate', self.launch)
        row.pack_start(self.command, True, True, 0)
        self.button(row, 'Launch', self.launch)
        box.pack_start(row, False, False, 0)
        self.message = Gtk.Label(xalign=0, wrap=True, selectable=True)
        box.pack_start(self.message, False, False, 0)
        self.profiles.connect('changed', self.selection_changed)
        self.refresh()
        self.timer = GLib.timeout_add_seconds(10, self.tick)

    def close(self, *_):
        self.closed = True
        if getattr(self, 'timer', None):
            GLib.source_remove(self.timer)
        if Gtk.main_level():
            Gtk.main_quit()

    def button(self, container, label, callback, grid_position=None):
        button = Gtk.Button(label=label)
        button.connect('clicked', callback)
        if grid_position:
            container.attach(button, *grid_position, 1, 1)
        else:
            container.pack_start(button, False, False, 0)
        self.buttons[label] = button
        return button

    @staticmethod
    def set_label(widget, text):
        if widget.get_text() != text:
            widget.set_text(text)

    def selected(self):
        return self.profiles.get_active_text()

    def sensitivities(self):
        state = self.statuses.get(self.selected(), {}).get('state')
        ready = not self.busy and self.available
        self.profiles.set_sensitive(not self.busy)
        self.buttons['Import'].set_sensitive(ready)
        self.buttons['Refresh'].set_sensitive(not self.busy)
        for label in ('Rename', 'Delete', 'Start'):
            self.buttons[label].set_sensitive(ready and state == 'stopped')
        for label in ('Stop', 'Check IP'):
            self.buttons[label].set_sensitive(ready and state == 'up')
        self.buttons['Launch'].set_sensitive(ready and state == 'up' and bool(self.command.get_text().strip()))

    def selection_changed(self, *_):
        if not self.updating:
            self.revision += 1
            self.set_label(self.message, '')
            self.render()

    def render(self):
        value = self.statuses.get(self.selected(), {})
        state = value.get('state', 'empty' if self.available else 'unavailable')
        peers = value.get('peers', [])
        descriptions = {'up': 'Running', 'stopped': 'Stopped', 'error': 'Unavailable', 'unavailable': 'Service unavailable', 'empty': 'No profiles'}
        self.set_label(self.state, descriptions.get(state, state))
        self.set_label(self.fields['Server'], '\n'.join(p['endpoint'] for p in peers) or '—')
        self.set_label(self.fields['Handshake'], '\n'.join(f"{p['handshake_age']} seconds ago" if p['handshake_age'] is not None else 'Waiting for first handshake' for p in peers) or '—')
        self.set_label(self.fields['Transfer'], f"↓ {sum(p['received'] for p in peers) / 1048576:.2f} MiB    ↑ {sum(p['sent'] for p in peers) / 1048576:.2f} MiB" if peers else '—')
        probe = self.exit_results.get(self.selected())
        if probe and (state != 'up' or probe['generation'] != value.get('generation')):
            self.exit_results.pop(self.selected(), None)
            probe = None
        self.set_label(self.fields['Exit IP'], f"{probe['ip']} · checked {probe['time']}" if probe else 'Not checked' if state == 'up' else '—')
        applications = value.get('applications', [])
        self.set_label(self.apps, '\n'.join(f"{app['name']}  (PID {app['pid']})" for app in applications) or 'No applications in this profile')
        label = f'Applications ({len(applications)})'
        if self.apps_expander.get_label() != label:
            self.apps_expander.set_label(label)
        if value.get('error'):
            self.set_label(self.message, value['error'])
        self.sensitivities()

    def work(self, function, done=None):
        """Foreground actions may disable controls; passive polling never does."""
        if self.busy:
            return
        self.revision += 1
        self.busy = True
        self.sensitivities()
        def finish(value, error):
            if self.closed:
                return False
            self.busy = False
            if error:
                self.set_label(self.message, str(error))
            elif done:
                done(value)
            self.sensitivities()
            return False
        def worker():
            try:
                value = function()
                GLib.idle_add(finish, value, None)
            except Exception as error:
                GLib.idle_add(finish, None, error)
        threading.Thread(target=worker, daemon=True).start()

    def apply_profiles(self, profiles, preferred=None):
        selected = preferred or self.selected()
        self.available = True
        self.statuses = {p['profile']: p for p in profiles}
        names = list(self.statuses)
        # Preserve selection, focus and the model for all ordinary refreshes.
        if names != self.names:
            self.updating = True
            self.profiles.remove_all()
            for name in names:
                self.profiles.append_text(name)
            if names:
                self.profiles.set_active(names.index(selected) if selected in names else 0)
            self.names = names
            self.updating = False
        self.exit_results = {name: probe for name, probe in self.exit_results.items() if self.statuses.get(name, {}).get('state') == 'up' and self.statuses[name].get('generation') == probe['generation']}
        self.render()

    def unavailable(self, error):
        self.available = False
        self.exit_results.clear()
        for value in self.statuses.values():
            value.update(state='unavailable', peers=[], applications=[])
        self.render()
        self.set_label(self.message, str(error))

    def refresh(self, preferred=None):
        def load():
            try:
                return client.call('list')['profiles'], None
            except (OSError, ValueError, RuntimeError) as error:
                return None, error
        def done(result):
            profiles, error = result
            if error:
                self.unavailable(error)
            else:
                self.set_label(self.message, '')
                self.apply_profiles(profiles, preferred)
        self.work(load, done)

    def tick(self):
        # Only a running selection needs live counters. No whole-list rebuild,
        # spinner, focus change, or control sensitivity change during polling.
        if self.closed:
            return False
        name = self.selected()
        if self.busy or self.polling or self.modal_depth or (self.available and self.statuses.get(name, {}).get('state') != 'up'):
            return True
        self.polling = True
        revision = self.revision
        recovering = not self.available
        def finish(value, error):
            self.polling = False
            if self.closed or revision != self.revision:
                return False
            if error:
                self.unavailable(error)
            elif recovering:
                self.set_label(self.message, '')
                self.apply_profiles(value['profiles'])
            else:
                self.statuses[name] = value
                self.render()
            return False
        def worker():
            try:
                value = client.call('list') if recovering else client.call('status', profile=name)
                GLib.idle_add(finish, value, None)
            except Exception as error:
                GLib.idle_add(finish, None, error)
        threading.Thread(target=worker, daemon=True).start()
        return True

    def action(self, op):
        name = self.selected()
        state = self.statuses.get(name, {}).get('state')
        if not name or self.busy or not self.available or (op == 'start' and state != 'stopped') or (op == 'stop' and state != 'up'):
            return
        self.exit_results.pop(name, None)
        def done(value):
            self.statuses[name] = value
            self.set_label(self.message, 'Stopped. Relaunch affected apps after starting again.' if op == 'stop' else '')
            self.render()
        self.work(lambda: client.call(op, profile=name), done)

    def run_dialog(self, dialog):
        self.modal_depth += 1
        try:
            return dialog.run()
        finally:
            self.modal_depth -= 1
            dialog.destroy()

    def confirm(self, message):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL, text=message)
        return self.run_dialog(dialog) == Gtk.ResponseType.OK

    def prompt(self, title, initial=''):
        dialog = Gtk.Dialog(title=title, transient_for=self, modal=True)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'OK', Gtk.ResponseType.OK)
        entry = Gtk.Entry(text=initial, activates_default=True)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.get_content_area().add(entry)
        dialog.show_all()
        value = []
        dialog.connect('response', lambda *_: value.append(entry.get_text()))
        return value[0] if self.run_dialog(dialog) == Gtk.ResponseType.OK else None

    def stop(self, *_):
        value = self.statuses.get(self.selected(), {})
        if value.get('state') != 'up':
            return
        if value.get('applications') and not self.confirm('Stop this profile? Its applications will disconnect and need a full relaunch.'):
            return
        self.action('stop')

    def rename(self, *_):
        name = self.selected()
        new = self.prompt('Rename profile', name) if name else None
        if new and new != name:
            self.work(lambda: client.call('rename', profile=name, new_name=new), lambda _: self.refresh(preferred=new))

    def remove(self, *_):
        name = self.selected()
        if name and self.confirm('Delete ' + name + ' from AppWire?'):
            self.work(lambda: client.call('remove', profile=name), lambda _: self.refresh())

    def probe(self, *_):
        name = self.selected()
        value = self.statuses.get(name, {})
        if value.get('state') != 'up' or self.busy:
            return
        generation = value.get('generation')
        self.exit_results.pop(name, None)
        self.render()
        def check():
            ip = client.probe(name)
            current = client.call('status', profile=name)
            if current.get('generation') != generation or current['state'] != 'up':
                raise RuntimeError('Profile changed during the IP check. Check again.')
            return ip
        def done(ip):
            stamp = datetime.datetime.now().astimezone().strftime('%H:%M:%S')
            self.exit_results[name] = {'ip': ip, 'time': stamp, 'generation': generation}
            self.set_label(self.message, '')
            self.render()
        self.work(check, done)

    def import_config(self, *_):
        dialog = Gtk.FileChooserDialog(title='Import WireGuard configurations', transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dialog.set_select_multiple(True)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Import', Gtk.ResponseType.OK)
        chosen = []
        dialog.connect('response', lambda *_: chosen.extend(dialog.get_filenames()))
        files = chosen if self.run_dialog(dialog) == Gtk.ResponseType.OK else []
        imports = []
        for filename in files:
            name = self.prompt('Profile name', local.suggested_name(filename))
            if not name:
                continue
            replace = name in self.statuses or any(item[0] == name for item in imports)
            if replace and not self.confirm('Replace ' + name + '? The profile must be stopped.'):
                continue
            imports.append((name, filename, replace))
        def perform():
            results = []
            for name, filename, replace in imports:
                try:
                    client.call('import', profile=name, config=read_config(filename), replace=replace)
                    results.append(name + ': imported')
                except (OSError, ValueError, RuntimeError) as error:
                    results.append(name + ': ' + str(error))
            return results, client.call('list')['profiles']
        def done(result):
            results, profiles = result
            self.apply_profiles(profiles)
            self.set_label(self.message, '\n'.join(results))
        if imports:
            self.work(perform, done)

    def launch(self, *_):
        name = self.selected()
        if self.busy or not self.available or self.statuses.get(name, {}).get('state') != 'up':
            return
        try:
            argv = shlex.split(self.command.get_text())
            if not argv:
                return
            process = subprocess.Popen(['/usr/bin/appwire', 'run', '--log', name, '--', *argv], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self.set_label(self.message, 'Launch requested in ' + name + '.')
            def poll():
                if self.closed:
                    return False
                if process.poll() is None:
                    return True
                if process.returncode:
                    self.set_label(self.message, f'Launch exited with code {process.returncode}. Log: {local.directory() / "applications.log"}')
                return False
            GLib.timeout_add_seconds(1, poll)
        except (OSError, ValueError) as error:
            self.set_label(self.message, str(error))


def main():
    win = Window()
    win.show_all()
    Gtk.main()
    return 0
