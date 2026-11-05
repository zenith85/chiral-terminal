"""Single-instance application with any number of windows.

Every `chiral ...` call is forwarded to the running Chiral over D-Bus. Calls made from a shell inside a
Chiral window (nano pop-outs, $EDITOR, chiral -f ...) go back to that same window; `chiral --new-window`
(the Ctrl+Alt+F shortcut) opens another window; other calls go to the window you used last.
"""
import json
import os
import time

from gi.repository import Gio, GLib, Gtk

from . import config

USAGE = '''usage: chiral [PATH[:LINE]]...        open a folder or file (files open in a sub-terminal)
       chiral --new-window [PATH]      open another Chiral window (the Ctrl+Alt+F shortcut does this)
       chiral -f "CMD"                 run CMD in a new sub-terminal
       chiral -x FILE                  open FILE in the hex viewer
       chiral open [PATH]              show PATH in Nautilus
       chiral settings                 open the settings window
       chiral restart                  restart on the latest code; every window, column, terminal and
                                      agent comes back in its folder (Claude agents continue their chat)
       chiral --popout [--wait] -- PROGRAM ARGS...
                                      run PROGRAM in a sub-terminal (used by the shell integration;
                                      --wait returns when it closes, so it works as $EDITOR)

keys:  Shift+→ new terminal column   Shift+← close it   Shift+↑ command bar   Shift+↓ windows
       Ctrl+Shift+F files   Ctrl+←/→ move focus   Shift+↑ → "AI agent" opens Claude in a floating window
       Ctrl+Shift+T new sub-terminal   Ctrl+Shift+W close it   Ctrl+Shift+E Claude explains the last failure
       Ctrl+Shift+arrows reach Chiral even while nano/vim are running
'''


class CliError(Exception):
    pass


def parse(args):
    opts = {'paths': [], 'float': None, 'hex': None, 'open': None, 'settings': False,
            'popout': None, 'wait': False, 'new_window': False, 'restart': False, 'restore': None}
    i = 0
    if args and args[0] == 'open':
        opts['open'] = args[1] if len(args) > 1 else '.'
        return opts
    if args and args[0] == 'restart':
        opts['restart'] = True
        return opts
    if args[:1] == ['--restore'] and len(args) > 1:     # used by `chiral restart` itself
        opts['restore'] = args[1]
        return opts
    if args and args[0] == 'settings':
        opts['settings'] = True
        return opts
    while i < len(args):
        a = args[i]
        if a == '--wait':
            opts['wait'] = True
        elif a == '--new-window':
            opts['new_window'] = True
        elif a == '--popout':
            rest = args[i + 1:]
            if rest[:1] == ['--']:
                rest = rest[1:]
            if not rest:
                raise CliError('--popout needs a program')
            opts['popout'] = rest
            return opts
        elif a in ('-f', '--float'):
            if i + 1 >= len(args):
                raise CliError('%s needs a command' % a)
            opts['float'] = args[i + 1]
            i += 1
        elif a in ('-x', '--hex'):
            if i + 1 >= len(args):
                raise CliError('%s needs a file' % a)
            opts['hex'] = args[i + 1]
            i += 1
        elif a.startswith('-') and a != '-':
            raise CliError('unknown option %s' % a)
        else:
            opts['paths'].append(a)
        i += 1
    return opts


class ChiralApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=os.environ.get('CHIRAL_APP_ID') or 'org.chiral.Chiral',  # another id: a separate test instance
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE
                         | Gio.ApplicationFlags.SEND_ENVIRONMENT)   # so calls from a Chiral shell find their window
        self.cfg = None
        self.windows = {}            # window id -> MainWindow
        self.next_window_id = 1
        self.last_window = None
        self.waiting = {}
        self.restart_file = None     # set by request_restart: __main__ starts the new code with it
        self._restart_asked = 0.0

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.cfg, self.cfg_errors = config.load()

    @property
    def window(self):
        """The window you used last (or any open one)."""
        if self.last_window in self.windows.values():
            return self.last_window
        return next(iter(self.windows.values()), None)

    def _new_window(self, start):
        from .window import MainWindow
        # dialogs and tooltips (shared by all windows) stay dark; each window paints its own theme
        Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', True)
        if self.windows:
            self.cfg, _errors = config.load()       # the latest saved settings (including the last theme chosen)
        wid = self.next_window_id
        self.next_window_id += 1
        win = MainWindow(self, start, wid)
        self.windows[wid] = win
        win.connect('destroy', self._on_window_destroy, wid)
        win.connect('focus-in-event', lambda *_: (setattr(self, 'last_window', win), False)[1])
        win.show_all()
        self.last_window = win
        if self.cfg_errors:
            win.toast('settings: ' + self.cfg_errors[0])
        return win

    def do_command_line(self, cl):
        args = [a if isinstance(a, str) else a.decode() for a in cl.get_arguments()[1:]]
        cwd = cl.get_cwd() or os.getcwd()
        try:
            opts = parse(args)
        except CliError as e:
            if self.window:
                self.window.toast('chiral: %s' % e)
            return 2
        caller = None                        # the Chiral window whose shell ran this command, if any
        for item in cl.get_environ() or []:
            item = item if isinstance(item, str) else item.decode(errors='ignore')
            if item.startswith('CHIRAL_WINDOW_ID='):
                try:
                    caller = self.windows.get(int(item.split('=', 1)[1]))
                except ValueError:
                    pass

        def resolve(p):
            return os.path.normpath(os.path.join(cwd, os.path.expanduser(p)))

        if opts['restore']:
            self.restore(opts['restore'])
            return 0
        if opts['restart'] and self.windows:
            self.request_restart(caller or self.window)
            return 0

        first = opts['new_window'] or (caller is None and not self.windows)
        if first:
            start = cwd
            for p in opts['paths']:
                if os.path.isdir(resolve(p)):
                    start = resolve(p)
                    break
            win = self._new_window(start)
        else:
            win = caller or self.window

        if opts['popout']:
            if opts['wait']:
                key = id(cl)
                self.waiting[key] = (win.window_id, cl)

                def release(status, key=key):
                    held = self.waiting.pop(key, None)
                    if held is not None:
                        held[1].set_exit_status(status)
                win.popout(opts['popout'], cwd, on_exit=release)
            else:
                win.popout(opts['popout'], cwd)
            return 0
        if opts['open'] is not None:
            win.nautilus(resolve(opts['open']))
            return 0
        if opts['settings']:
            win.open_settings()
        if opts['float']:
            win.run_float(opts['float'], cwd=cwd)
        if opts['hex']:
            win.open_file(resolve(opts['hex']), hex_view=True)
        for p in opts['paths']:
            full = resolve(p)
            if first and full == win.cwd:
                continue
            if os.path.isdir(full):
                win.new_shell(cwd=full)
            else:
                path, _, line = full.rpartition(':')
                if line.isdigit() and path:
                    win.open_file(path)     # editors differ in how they take a line; open the file
                else:
                    win.open_file(full)
        if not opts['popout']:
            win.present()
        return 0

    # --- restart chiral: the latest code, the same windows ---
    def request_restart(self, win):
        busy = sorted({n for w in self.windows.values() for n in w.busy_programs()})
        now = time.monotonic()
        if busy and now - self._restart_asked > 15:
            self._restart_asked = now
            win.toast('restart closes %s (unsaved work is lost). Restart again within 15 s to go ahead'
                      % ', '.join(busy[:4]))
            return
        wins = sorted(self.windows.values(), key=lambda w: w is self.window)   # the one you used last ends on top
        state = [w.restart_state() for w in wins]
        path = os.path.join(GLib.get_user_runtime_dir(), 'chiral-restore-%d.json' % os.getpid())
        try:
            with open(path, 'w') as f:
                json.dump(state, f)
        except OSError as e:
            win.toast('could not restart: %s' % e)
            return
        self.restart_file = path
        for w in wins:
            w.destroy()
        self.quit()

    def restore(self, path):
        try:
            with open(path) as f:
                states = json.load(f)
        except (OSError, ValueError):
            states = []
        try:
            os.unlink(path)
        except OSError:
            pass
        win = None
        for st in states or [{}]:
            cwd = st.get('cwd')
            win = self._new_window(cwd if cwd and os.path.isdir(cwd) else os.path.expanduser('~'))
            win.restore_state(st)
        win.present()
        win.toast('Chiral restarted')

    def _on_window_destroy(self, _win, wid):
        self.windows.pop(wid, None)
        for key, (owner, cl) in list(self.waiting.items()):
            if owner == wid:
                cl.set_exit_status(1)
                self.waiting.pop(key, None)
