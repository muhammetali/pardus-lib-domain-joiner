#!/usr/bin/env python3
"""Capture the installed GUI's real invalid-OU flow in the disposable lab."""
import json
import os
from pathlib import Path
import runpy
import socket
import sys
import time

assert os.geteuid() == 0
assert socket.gethostname() == "pardus-domain-lab"
assert Path("/root/domain-validation-lab").is_file()
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, "/usr/share/pardus/pardus-domain-joiner/src")
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gdk

started = time.monotonic()
state = {"started_join": False, "captured": False}

def timeout():
    state["error"] = "GUI timeout"
    app = Gtk.Application.get_default()
    if app:
        app.quit()
    return False

def advance():
    app = Gtk.Application.get_default()
    if app is None or app.window is None:
        return True
    ui = app.window
    state["ui"] = ui
    state["app"] = app
    if time.monotonic() - started > 60:
        state["error"] = "GUI timeout"
        app.quit()
        return False
    if not state["started_join"]:
        if ui.main_stack.get_visible_child_name() != "main":
            return True
        ui.domain_entry.set_text("missing.pdj.invalid")
        ui.username_entry.set_text("test-user")
        ui.password_entry.set_text("not-a-real-password")
        ui.sssd_radio.set_active(True)
        ui.ou_specific_radio.set_active(True)
        ui.ou_path_entry.set_text("computers")
        # Use the application's normal button handlers and privileged Actions.py.
        ui.on_prejoin_btn_clicked(None)
        assert ui.main_stack.get_visible_child_name() == "prejoin"
        ui.on_join_btn_clicked(None)
        state["started_join"] = True
        return True
    if ui.joining_process_pid is not None:
        return True
    # Allow the output watches and rendering to finish before capture.
    GLib.timeout_add(1000, capture)
    return False

def capture():
    ui = state["ui"]
    window = ui.window.get_window()
    pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, window.get_width(), window.get_height())
    pixbuf.savev(str(output / "invalid-ou.png"), "png", [], [])
    result = {
        "page": ui.main_stack.get_visible_child_name(),
        "title": ui.joining_title_label.get_text(),
        "log": ui.joining_log_label.get_text(),
        "backend": ui.model.connection_type,
        "ou": ui.model.organizational_unit,
        "domain": ui.model.domain,
        "actions_path": "/usr/share/pardus/pardus-domain-joiner/src/Actions.py",
        "scope": "Installed full GUI, real privileged helper, deliberately nonexistent .invalid domain; no AD membership.",
    }
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    state["captured"] = True
    state["app"].quit()
    return False

GLib.timeout_add(250, advance)
GLib.timeout_add_seconds(60, timeout)
sys.argv = ["/usr/share/pardus/pardus-domain-joiner/src/Main.py"]
runpy.run_path(sys.argv[0], run_name="__main__")
if not state["captured"]:
    raise SystemExit(state.get("error", "GUI exited before capture"))
