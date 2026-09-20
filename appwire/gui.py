"""Small GTK3 frontend; all service work stays off GTK's main thread."""

import os
import shlex
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from . import client
from .config import MAX_CONFIG


class Window(Gtk.Window):
    def __init__(self):
        super().__init__(title="AppWire")
        self.set_default_size(720, 500)
        self.connect("destroy", Gtk.main_quit)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=18)
        self.add(box)
        title = Gtk.Label(label="WireGuard for selected apps", xalign=0)
        box.pack_start(title, False, False, 0)
        self.profiles = Gtk.ComboBoxText()
        box.pack_start(self.profiles, False, False, 0)
        row = Gtk.Box(spacing=8)
        box.pack_start(row, False, False, 0)
        for label, action in [
            ("Import…", self.import_config),
            ("Delete", self.delete_profile),
            ("Start", lambda *_: self.action("start")),
            ("Stop", lambda *_: self.action("stop")),
            ("Refresh", lambda *_: self.refresh()),
            ("Check exit IP", self.probe),
        ]:
            button = Gtk.Button(label=label)
            button.connect("clicked", action)
            row.pack_start(button, False, False, 0)
        self.details = Gtk.TextView(
            editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR
        )
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(200)
        scroll.add(self.details)
        box.pack_start(scroll, True, True, 0)
        self.command = Gtk.Entry(
            placeholder_text="Application and arguments, for example: faugus-launcher"
        )
        box.pack_start(self.command, False, False, 0)
        launch = Gtk.Button(label="Launch in selected profile")
        launch.connect("clicked", self.launch)
        box.pack_start(launch, False, False, 0)
        self.message = Gtk.Label(
            label="Start a profile before launching. Stop disconnects apps still using it.",
            xalign=0,
            wrap=True,
        )
        box.pack_start(self.message, False, False, 0)
        self.profiles.connect("changed", lambda *_: self.action("status"))
        self.busy = False
        self.refresh()
        GLib.timeout_add_seconds(5, self.tick)

    def tick(self):
        if not self.busy:
            self.action("status", quiet=True)
        return True

    def work(self, function, done=None):
        if self.busy:
            return
        self.busy = True

        def finish(value, error):
            self.busy = False
            if error:
                self.message.set_text(str(error))
            elif done:
                done(value)
            return False

        def worker():
            try:
                value = function()
                GLib.idle_add(finish, value, None)
            except Exception as error:
                GLib.idle_add(finish, None, error)

        threading.Thread(target=worker, daemon=True).start()

    def selected(self):
        return self.profiles.get_active_text()

    def show_status(self, value):
        lines = [value["profile"], "State: " + value["state"]]
        if value.get("namespace"):
            lines.append("Namespace: " + value["namespace"])
        for peer in value.get("peers", []):
            age = peer["handshake_age"]
            lines.extend(
                [
                    "",
                    "Endpoint: " + peer["endpoint"],
                    "Handshake: "
                    + (
                        f"{age} seconds ago"
                        if age is not None
                        else "waiting for first handshake"
                    ),
                    f"Received: {peer['received'] / 1048576:.2f} MiB    Sent: {peer['sent'] / 1048576:.2f} MiB",
                ]
            )
        apps = value.get("applications", [])
        if apps:
            lines.extend(
                ["", "Applications:"]
                + [f"  {a['name']}  (PID {a['pid']})" for a in apps]
            )
        self.details.get_buffer().set_text("\n".join(lines))

    def refresh(self):
        def done(value):
            selected = self.selected()
            names = [p["profile"] for p in value["profiles"]]
            self.profiles.remove_all()
            for name in names:
                self.profiles.append_text(name)
            if names:
                self.profiles.set_active(
                    names.index(selected) if selected in names else 0
                )
            else:
                self.message.set_text(
                    "Import a standard WireGuard configuration to begin."
                )

        self.work(lambda: client.call("list"), done)

    def action(self, op, quiet=False):
        name = self.selected()
        if name:
            self.work(lambda: client.call(op, profile=name), self.show_status)

    def probe(self, *_):
        name = self.selected()
        if name:
            self.work(
                lambda: client.probe(name),
                lambda ip: self.message.set_text("Verified IPv4 exit: " + ip),
            )

    def launch(self, *_):
        name = self.selected()
        try:
            argv = shlex.split(self.command.get_text())
            if name and argv:
                # Launch unprivileged CLI, preserving GTK/session environment.
                directory = (
                    Path(
                        os.environ.get(
                            "XDG_STATE_HOME", str(Path.home() / ".local/state")
                        )
                    )
                    / "appwire"
                )
                directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                log = directory / "applications.log"
                fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                try:
                    process = subprocess.Popen(
                        ["/usr/bin/appwire", "run", name, "--", *argv],
                        stdin=subprocess.DEVNULL,
                        stdout=fd,
                        stderr=fd,
                        start_new_session=True,
                    )
                finally:
                    os.close(fd)
                self.message.set_text("Launch requested. Application log: " + str(log))

                def poll():
                    if process.poll() is None:
                        return True
                    self.message.set_text(
                        f"Application exited ({process.returncode}). Log: {log}"
                    )
                    return False

                GLib.timeout_add_seconds(1, poll)
        except (ValueError, OSError) as error:
            self.message.set_text(str(error))

    def delete_profile(self, *_):
        name = self.selected()
        if not name:
            return

        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=f'Delete profile "{name}"?',
        )
        dialog.format_secondary_text(
            "This permanently removes the imported WireGuard configuration."
        )
        dialog.add_buttons(
            "Cancel",
            Gtk.ResponseType.CANCEL,
            "Delete",
            Gtk.ResponseType.OK,
        )

        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return

        def done(_):
            self.message.set_text(f"Deleted profile: {name}")
            self.details.get_buffer().set_text("")
            self.refresh()

        self.work(
            lambda: client.call("remove", profile=name),
            done,
        )

    def import_config(self, *_):
        dialog = Gtk.FileChooserDialog(
            title="Import WireGuard config",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            "Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK
        )
        if dialog.run() == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            dialog.destroy()
            name_dialog = Gtk.Dialog(
                title="Profile name", transient_for=self, modal=True
            )
            name_dialog.add_buttons(
                "Cancel", Gtk.ResponseType.CANCEL, "Import", Gtk.ResponseType.OK
            )
            entry = Gtk.Entry(placeholder_text="proton-us")
            name_dialog.get_content_area().add(entry)
            name_dialog.show_all()
            if name_dialog.run() == Gtk.ResponseType.OK:
                name = entry.get_text()

                def load():
                    with open(filename) as source:
                        text = source.read(MAX_CONFIG + 1)
                    return client.call("import", profile=name, config=text)

                self.work(load, lambda _: self.refresh())
            name_dialog.destroy()
        else:
            dialog.destroy()


def main():
    win = Window()
    win.show_all()
    Gtk.main()
    return 0
