"""The Chiral window: a plain terminal with four hidden edges.

  Shift+↑  command bar        Shift+←  close a terminal column (the focused one, else the last)
  Shift+↓  window bar         Shift+→  new terminal column on the right (focused one: bigger font)
  AI agents: Shift+↑ → "AI agent" opens Claude in a floating window that watches your terminals
  Ctrl+O or Ctrl+Shift+F file tree (or touch the left edge with the mouse); moving through it shows a live
        preview window: folders as a shell there, binaries in hex, text read-only. Space keeps the preview
  Ctrl+Shift+T new sub-terminal · Ctrl+Shift+W close it · Ctrl+Shift+E Claude explains last failure
  Ctrl+Shift+C / V copy / paste · Ctrl + / - / 0 font of the focused terminal
  Ctrl + mouse wheel: zoom the terminal under the mouse · Ctrl+0 back to automatic size
  Ctrl+← / Ctrl+→ move focus: file tree, main terminal, sub-terminals 1..n, Claude (open ones only)

"smart" Shift+arrows: when a program such as nano is running in the focused terminal, Shift+arrows go
to that program; Ctrl+Shift+arrows always reach Chiral.
"""
import itertools
import os
import shlex
import subprocess
import sys
import time

from gi.repository import GLib, Gdk, Gio, Gtk, Vte

from . import config, fonts, shell, themes
from .bars import CommandBar, Toast, WindowBar
from .awareness import AwarenessBar
from .agents import AgentManager
from . import imageview
from .session import RemoteView, ShareServer
from .side import Column
from .strands import StrandField
from .subwin import SubWindow
from .tree import FileTree

EDGE_KEYS = {Gdk.KEY_Left: 'uncolumn', Gdk.KEY_Right: 'column', Gdk.KEY_Down: 'bar', Gdk.KEY_Up: 'cmd'}
MODS = Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.SUPER_MASK
SHIFT = Gdk.ModifierType.SHIFT_MASK
CTRL_SHIFT = Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK
CTRL = Gdk.ModifierType.CONTROL_MASK
CONTEXT_ENTRIES = 12
BG_FRAME_MS = 80            # strands background: ~12 frames a second
_seeds = itertools.count(7)
CONTEXT_LINES = 60


def _rgba(hex_color):
    c = Gdk.RGBA()
    c.parse(hex_color)
    return c


BORDER = 2   # px; dim when unfocused, accent color on the focused terminal


def framed(child):
    """Wrap a terminal in a border that lights up while it has focus."""
    frame = Gtk.EventBox()
    frame.get_style_context().add_class('chiral-frame')
    for side in ('start', 'end', 'top', 'bottom'):   # margins sit inside the frame, which paints them
        getattr(child, 'set_margin_' + side)(BORDER)
    frame.add(child)
    return frame


def set_lit(frame, on):
    ctx = frame.get_style_context()
    (ctx.add_class if on else ctx.remove_class)('focused')


def _unpack(result):
    """GDK getters return (found, value) or just value depending on the event: accept both."""
    if isinstance(result, tuple):
        return (bool(result[0]), result[1]) if len(result) == 2 else (bool(result[0]), result[1:])
    return True, result


def is_binary(path):
    try:
        with open(path, 'rb') as f:
            chunk = f.read(8192)
    except OSError:
        return False
    if b'\0' in chunk:
        return True
    try:
        chunk.decode('utf-8')
    except UnicodeDecodeError as e:
        return e.start < len(chunk) - 4      # a cut multi-byte char at the end is fine
    return False


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app, cwd, window_id=1):
        super().__init__(application=app, title='Chiral Terminal')
        self.window_id = window_id
        self.app = app
        self.cfg = app.cfg
        self.cwd = cwd
        self.theme, self.accent = themes.get(self.cfg)
        self.runtime = shell.Runtime(window_id)
        self.subs = []
        self.focused_sub = None
        self.last_term = None
        self.next_sid = 1
        self.hover_open = set()
        self.context = []
        self.set_default_size(1200, 760)
        self._main_fit_source = 0
        self.main_font_size = None
        self.active_tile = None
        self.preview = None
        self.settings_window = None
        self.last_saved_settings = None
        self._bg_t0 = time.monotonic()
        self._bg_frames = 0

        self.css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)
        # the floating layer covers everything below the top bar: tree, main terminal and all columns,
        # so sub-terminals and AI agent windows float above all of them
        self.overlay = Gtk.Overlay()
        outer.pack_end(self.overlay, True, True, 0)
        root = Gtk.Box()
        self.overlay.add(root)
        self.tiles = Gtk.Box(homogeneous=True)       # main terminal + columns, equal widths
        root.pack_start(self.tiles, True, True, 0)
        self.columns = []

        self.main_term = self.make_terminal()
        self.main_term.chiral_is_app = False
        self.main_term.connect('child-exited', lambda *_: self.close())
        self.main_frame = framed(self.main_term)
        self.tiles.pack_start(self.main_frame, True, True, 0)

        # hidden edges
        self.tree = FileTree(self)
        self.bar = WindowBar(self)
        self.cmd = CommandBar(self)
        self.agents = AgentManager(self)
        self.share = ShareServer(self)            # N: share this window's terminals with your team
        self.aware = AwarenessBar(self)           # top bar: what is in the focused terminal's folder
        outer.pack_start(self.aware, False, False, 0)
        self.revealers = {
            'tree': self._revealer(self.tree, Gtk.RevealerTransitionType.SLIDE_RIGHT, Gtk.Align.START, Gtk.Align.FILL),
            'bar': self._revealer(self.bar, Gtk.RevealerTransitionType.SLIDE_UP, Gtk.Align.FILL, Gtk.Align.END),
            'cmd': self._revealer(self.cmd, Gtk.RevealerTransitionType.SLIDE_DOWN, Gtk.Align.CENTER, Gtk.Align.START),
        }
        self.left_zone = self._hot_zone(Gtk.Align.START, Gtk.Align.FILL, 3, -1, 'tree')
        self.bottom_zone = self._hot_zone(Gtk.Align.FILL, Gtk.Align.END, -1, 3, 'bar')
        self.toast_widget = Toast()
        self.top_layers = [self.left_zone, self.bottom_zone, self.revealers['bar'],
                           self.revealers['cmd'], self.toast_widget]
        for w in self.top_layers:
            self.overlay.add_overlay(w)
        # side panels take their own space: the main terminal squeezes instead of being covered
        root.pack_start(self.revealers['tree'], False, False, 0)
        root.reorder_child(self.revealers['tree'], 0)
        self.tree.connect('leave-notify-event', self._on_leave, 'tree')
        self.bar.connect('leave-notify-event', self._on_leave, 'bar')
        self.revealers['cmd'].connect('notify::child-revealed', self._restore_focus_if_hidden)

        self.connect('key-press-event', self._on_key)
        self.connect('set-focus', self._on_set_focus)
        self.connect('destroy', lambda *_: (self.share.stop(), self.runtime.cleanup()))

        self.apply_config()
        self.spawn(self.main_term, role='main', win=0, cwd=cwd)
        self.last_term = self.main_term
        self.aware.follow(cwd)
        GLib.timeout_add(400, self._poll_events)
        GLib.timeout_add(BG_FRAME_MS, self._bg_tick)
        self.main_frame.connect('size-allocate', lambda *_: self._schedule_main_fit())

        monitor_file = Gio.File.new_for_path(config.CONFIG_PATH)
        self.cfg_monitor = monitor_file.monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.cfg_monitor.connect('changed', self._on_config_changed)

    # ---------- building blocks ----------
    def _revealer(self, child, transition, halign, valign):
        r = Gtk.Revealer()
        r.set_transition_type(transition)
        r.set_halign(halign)
        r.set_valign(valign)
        r.add(child)
        return r

    def _hot_zone(self, halign, valign, w, h, panel):
        zone = Gtk.EventBox()
        zone.set_visible_window(False)
        zone.set_halign(halign)
        zone.set_valign(valign)
        zone.set_size_request(w, h)
        zone.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK)
        zone.connect('enter-notify-event', lambda *_: self._hover(panel))
        return zone

    def make_terminal(self):
        t = Vte.Terminal()
        t.set_scrollback_lines(10000)
        t.set_mouse_autohide(True)
        t.set_audible_bell(False)
        t.chiral_pid = None
        t.chiral_sub = None
        t.chiral_is_app = False
        t.chiral_keys_first = False    # True: Chiral's keys win even while a program runs (agents, previews)
        t.chiral_column = None
        t.chiral_font = None
        t.chiral_zoom = 0             # main / Claude: points added to the configured size
        t.chiral_scroll = 0.0
        t.connect('scroll-event', self._on_scroll)
        t.chiral_field = StrandField(next(_seeds))
        t.set_clear_background(False)      # we paint the background (and the strands) ourselves
        t.connect('draw', self._draw_background)
        self._style_terminal(t)
        return t

    def _draw_background(self, t, cr):
        """Runs before the terminal draws its text: background colour, then the strands."""
        th = self.theme
        bg, fg = _rgba(th['bg']), _rgba(th['fg'])
        cr.set_source_rgb(bg.red, bg.green, bg.blue)
        cr.paint()
        if self.cfg.get('background', 'strands') == 'strands':
            t.chiral_field.draw(cr, t.get_allocated_width(), t.get_allocated_height(),
                               time.monotonic() - self._bg_t0, (fg.red, fg.green, fg.blue))
        return False

    @staticmethod
    def _count_entries(folder, limit=2000):
        """(folders, files) directly inside `folder`, hidden ones left out; stops counting at `limit`."""
        dirs = files = 0
        try:
            with os.scandir(folder) as it:
                for n, e in enumerate(it):
                    if n >= limit:
                        break
                    if e.name.startswith('.'):
                        continue
                    try:
                        if e.is_dir():
                            dirs += 1
                        else:
                            files += 1
                    except OSError:
                        files += 1
        except OSError:
            pass
        return dirs, files

    def _update_strand_counts(self):
        """Each terminal's strands mirror its folder: one per entry, thick for folders, thin for files."""
        now = time.monotonic() - self._bg_t0
        for t in self.all_terminals():
            if not t.get_mapped():
                continue
            folder = self.cwd_of(t)
            if folder == getattr(t, 'chiral_strand_folder', None) and now - getattr(t, 'chiral_strand_time', -99) < 8:
                continue
            t.chiral_strand_folder, t.chiral_strand_time = folder, now
            before = t.chiral_field.counts
            t.chiral_field.set_counts(*self._count_entries(folder), now)
            if t.chiral_field.counts != before:
                t.queue_draw()

    def _bg_tick(self):
        """Move the strands: redraw visible terminals. Slow when Chiral is not the active window."""
        self._bg_frames += 1
        if self._bg_frames % 25 == 1 and self.cfg.get('background', 'strands') == 'strands':
            self._update_strand_counts()             # about every 2 seconds
        if (self.cfg.get('background', 'strands') != 'strands'
                or self.cfg.get('animations', 'normal') == 'off'):
            return True
        if not self.is_active() and self._bg_frames % 12:
            return True                              # about once a second in the background
        for t in self.all_terminals():
            if t.get_mapped():
                t.queue_draw()
        return True

    def _style_terminal(self, t):
        th = self.theme
        t.set_colors(_rgba(th['fg']), _rgba(th['bg']), [_rgba(c) for c in th['palette']])
        t.set_color_cursor(_rgba(self.accent))
        t.set_color_cursor_foreground(_rgba(th['bg']))
        t.set_cell_height_scale(float(self.cfg['font'].get('line_height', 1.0)))
        if t.chiral_sub is None:
            f = self.cfg['font']
            t.set_font(fonts.desc(f.get('family', 'Monospace'), self._zoomed(f.get('size', 12), t)))

    def spawn(self, term, role, win, cwd, argv=None, done=None, extra_env=None, env=None):
        argv = argv or self.runtime.shell_argv()
        if env is None:                      # env given: used as is (the locked team shell)
            env = self.runtime.env(self.cfg, role, win) + ['%s=%s' % kv for kv in (extra_env or {}).items()]

        def spawned(t, pid, error, *_):
            if error:
                t.feed(('\r\nchiral: could not start %s: %s\r\n' % (argv[0], error.message)).encode())
                return
            t.chiral_pid = pid
            if done:
                done(pid)
        term.spawn_async(Vte.PtyFlags.DEFAULT, cwd if os.path.isdir(cwd or '') else os.path.expanduser('~'),
                         argv, env, GLib.SpawnFlags.SEARCH_PATH, None, None, -1, None, spawned, None)

    # ---------- settings ----------
    def apply_config(self):
        self.theme, self.accent = themes.get(self.cfg)
        th, acc = self.theme, self.accent
        family = self.cfg['font'].get('family', 'Monospace')
        css = '''
        .chiral-panel {{ background-color: {pane}; color: {fg}; }}
        .chiral-panel treeview, .chiral-panel list, .chiral-panel row {{ background-color: {pane}; color: {fg}; font-family: "{family}"; }}
        .chiral-panel treeview:selected, .chiral-panel row:selected {{ background-color: {hdr}; color: {acc}; }}
        .chiral-panel label {{ font-family: "{family}"; }}
        .chiral-panel entry {{ background-color: {bg}; color: {fg}; font-family: "{family}"; border: 1px solid {acc};
                              border-radius: 0; box-shadow: none; padding: 5px 8px; caret-color: {acc}; }}
        .chiral-cmd {{ border: 1px solid {line}; border-top: none; }}
        separator {{ background-color: {line}; min-width: 1px; min-height: 1px; }}
        .chiral-sub, .chiral-frame {{ background-color: {dim}; }}
        .chiral-sub.focused, .chiral-frame.focused {{ background-color: {acc}; }}
        .chiral-sub {{ border-radius: 0; }}
        .chiral-sub.agent {{ border-radius: 9px; }}
        .chiral-title {{ background-color: {hdr}; color: {fg}; font-family: "{family}"; font-size: 9pt; }}
        .chiral-title label {{ padding-left: 6px; }}
        .chiral-sub.focused .chiral-title {{ background-color: {acc}; color: #0c0d0f; }}
        .chiral-title button {{ padding: 0 6px; min-height: 0; min-width: 0; border: none; background: none;
                               box-shadow: none; color: inherit; font-family: "{family}"; }}
        .chiral-meta {{ opacity: 0.75; }}
        .chiral-title button.chiral-tab {{ opacity: 0.55; }}
        .chiral-title button.chiral-tab.active {{ opacity: 1; font-weight: bold; }}
        .chiral-grip {{ background-image: linear-gradient(135deg, transparent 55%, {line} 55%); }}
        .chiral-sub.focused .chiral-grip {{ background-image: linear-gradient(135deg, transparent 55%, {acc} 55%); }}
        .chiral-bar button {{ padding: 1px 8px; min-height: 0; border: none; border-radius: 0; box-shadow: none;
                             background: {hdr}; color: {fg}; font-family: "{family}"; }}
        .chiral-bar button.focused {{ background: {acc}; color: #0c0d0f; }}
        .chiral-bar button.hidden-win {{ color: {dim}; }}
        .chiral-dim {{ color: {dim}; }}
        .chiral-card {{ padding: 6px; border-radius: 10px; }}
        .chiral-share {{ padding: 0 6px; border-radius: 4px; font-weight: bold; }}
        .chiral-share.on {{ background-color: {acc}; color: #101010; }}
        .chiral-sub.remote {{ background-color: {palette5}; }}
        .chiral-frame.team {{ background-color: {palette5}; }}
        .chiral-frame.team.focused {{ background-color: {acc}; }}
        .chiral-frame.buzz, .chiral-frame.focused.buzz, .chiral-frame.team.buzz, .chiral-frame.team.focused.buzz,
        .chiral-sub.buzz, .chiral-sub.focused.buzz, .chiral-sub.remote.buzz {{ background-color: {palette1}; }}
        .chiral-sub.remote.focused {{ background-color: {acc}; }}
        .chiral-settings stacksidebar row:selected {{ background-color: {acc}; color: #101010; }}
        .chiral-settings switch:checked {{ background-color: {acc}; border-color: {acc}; }}
        .chiral-card:hover {{ background-color: alpha({acc}, 0.12); }}
        .chiral-card.selected {{ background-color: alpha({acc}, 0.35); }}
        .chiral-aware {{ background-color: {pane}; color: {fg}; }}
        .chiral-aware label {{ font-family: "{family}"; font-size: 9pt; }}
        .chiral-aware-item {{ padding: 0 4px; min-height: 0; min-width: 0; border: none; box-shadow: none;
                             background: none; color: {fg}; }}
        .chiral-aware-item:hover {{ background: {hdr}; }}
        .chiral-aware-tag {{ color: {palette6}; }}
        .chiral-accent {{ color: {acc}; }}
        .chiral-toast {{ background-color: {hdr}; color: {fg}; border: 1px solid {line}; font-family: "{family}"; }}
        vte-terminal {{ padding: 2px 4px; }}
        '''.format(family=family, acc=acc, palette6=th['palette'][6], palette5=th['palette'][5],
                   palette1=th['palette'][1], **th)
        self.css.load_from_data(css.encode())
        if hasattr(self, 'aware'):
            self.aware.set_visible(bool(self.cfg.get('awareness', True)))
        Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', bool(th.get('dark', True)))
        ms = themes.ANIMATION_MS.get(self.cfg.get('animations', 'normal'), 120)
        for r in self.revealers.values():
            r.set_transition_duration(ms)
        self.toast_widget.set_transition_duration(ms)
        for t in self.all_terminals():
            self._style_terminal(t)
        self.main_font_size = None
        for t in self.tile_terms():
            t.chiral_font = None
        self._schedule_main_fit()
        for s in self.subs:
            s.font_size = None
            s.schedule_fit()

    def _on_config_changed(self, _mon, _file, _other, event):
        if event != Gio.FileMonitorEvent.CHANGES_DONE_HINT:
            return
        try:
            with open(config.CONFIG_PATH) as f:
                if f.read() == self.last_saved_settings:
                    return                  # our own save from the settings window: already applied
        except OSError:
            pass
        cfg, errors = config.load()
        self.app.cfg = self.cfg = cfg
        self.apply_config()
        self.toast('settings: ' + errors[0] if errors else 'settings applied')

    def set_setting(self, key, value):
        self.cfg[key] = value
        self.apply_config()
        try:
            config.set_top_level(key, value)
        except OSError as e:
            self.toast('could not save: %s' % e)

    def set_flag(self, key, value):
        self.cfg[key] = value
        self.apply_config()
        try:
            config.set_top_level_raw(key, 'true' if value else 'false')
        except OSError as e:
            self.toast('could not save: %s' % e)

    def open_settings(self, page=None):
        """The settings window (Shift+↑ → settings / appearance / font ...), optionally at one page."""
        from .settings_gui import SettingsWindow
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self)
            self.settings_window.connect('destroy', lambda *_: setattr(self, 'settings_window', None))
        if page:
            self.settings_window.stack.set_visible_child_name(page)
        self.settings_window.present()

    def open_settings_file(self):
        config.load()                 # creates the file on first use
        self.open_file(config.CONFIG_PATH)

    # ---------- terminals & focus ----------
    def all_terminals(self):
        return [self.main_term] + [c.term for c in self.columns] + [s.term for s in self.subs]

    def tile_terms(self):
        return [self.main_term] + [c.term for c in self.columns]

    # ---------- main terminal font follows its width ----------
    def _schedule_main_fit(self):
        if self._main_fit_source:
            GLib.source_remove(self._main_fit_source)
        self._main_fit_source = GLib.timeout_add(60, self._fit_main)

    @staticmethod
    def _zoomed(size, term):
        return max(6, min(40, size + term.chiral_zoom))

    def zoom_terminal(self, t, step):
        """step +1 / -1 bigger / smaller, 0 back to automatic size."""
        if t.chiral_sub:
            t.chiral_sub.zoom(step)
            size, name = t.chiral_sub.font_size, 'window %d' % self.sub_number(t.chiral_sub)
        else:
            base = self.cfg['font'].get('size', 12)
            t.chiral_zoom = 0 if step == 0 else max(6 - base, min(40 - base, t.chiral_zoom + step))
            t.chiral_font = None
            self.main_font_size = None
            self._fit_main()
            size = t.chiral_font if t.chiral_column else self.main_font_size
            name = 'column %d' % t.chiral_column.number() if t.chiral_column else 'main terminal'
        self.toast_widget.show_text('%s: %spt%s' % (name, size, '' if step == 0 else ' · Ctrl+0 resets'), seconds=1.2)
        self._keep_panels_on_top()

    def _on_scroll(self, t, ev):
        _ok, state = _unpack(ev.get_state())
        if state & Gdk.ModifierType.SHIFT_MASK and not state & Gdk.ModifierType.CONTROL_MASK and t.chiral_sub:
            return self._resize_scroll(t.chiral_sub, ev)   # Shift + wheel: resize a floating window
        if not state & Gdk.ModifierType.CONTROL_MASK:
            return False                      # plain wheel: scrollback as usual
        has_dir, direction = _unpack(ev.get_scroll_direction())
        if has_dir and direction == Gdk.ScrollDirection.UP:
            self.zoom_terminal(t, 1)
        elif has_dir and direction == Gdk.ScrollDirection.DOWN:
            self.zoom_terminal(t, -1)
        else:
            deltas = ev.get_scroll_deltas()
            if not deltas[0]:
                return True
            dy = deltas[-1]
            t.chiral_scroll -= dy              # touchpads send many small steps: add them up
            while abs(t.chiral_scroll) >= 1:
                step = 1 if t.chiral_scroll > 0 else -1
                t.chiral_scroll -= step
                self.zoom_terminal(t, step)
        return True

    def _resize_scroll(self, sub, ev):
        has_dir, direction = _unpack(ev.get_scroll_direction())
        if has_dir and direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.DOWN):
            steps = [1 if direction == Gdk.ScrollDirection.UP else -1]
        else:
            deltas = ev.get_scroll_deltas()
            if not deltas[0]:
                return True
            sub.chiral_resize_acc = getattr(sub, 'chiral_resize_acc', 0.0) - deltas[-1]
            steps = []
            while abs(sub.chiral_resize_acc) >= 1:
                step = 1 if sub.chiral_resize_acc > 0 else -1
                sub.chiral_resize_acc -= step
                steps.append(step)
        for step in steps:
            factor = 1.08 if step > 0 else 1 / 1.08
            w, h = sub.w * factor, sub.h * factor
            cx, cy = sub.x + sub.w / 2, sub.y + sub.h / 2          # grow / shrink around the centre
            sub.prev_geom = None
            sub.place(cx - w / 2, cy - h / 2, w, h)
        if steps:
            self.toast_widget.show_text('window %d: %d×%d' % (self.sub_number(sub), sub.w, sub.h), seconds=0.8)
            self._keep_panels_on_top()
        return True

    def _fit_main(self):
        """Full width: the configured size. Squeezed by the side panels: a smaller font that keeps
        about the same number of columns, never below auto_min."""
        self._main_fit_source = 0
        if self.columns:
            self._fit_tiles()
            return False
        f = self.cfg['font']
        base = self._zoomed(f.get('size', 12), self.main_term)
        size = base
        if f.get('main_auto', True):
            full_w = self.get_child().get_allocated_width() - 2 * BORDER
            now_w = self.main_term.get_allocated_width()
            if now_w < full_w - 8:
                family = f.get('family', 'Monospace')
                cols = int(full_w / fonts.char_width(self.main_term, family, base))
                size = fonts.fit(self.main_term, now_w, dict(f, auto_columns=cols, auto_max=base,
                                                             auto_min=min(f.get('auto_min', 7), base)))
        if size != self.main_font_size:
            self.main_font_size = size
            self.main_term.set_font(fonts.desc(f.get('family', 'Monospace'), size))
        return False

    def _fit_tiles(self):
        """Main terminal and columns: the focused one at its normal size, the others smaller."""
        f = self.cfg['font']
        family = f.get('family', 'Monospace')
        drop = int(f.get('unfocused_drop', 3))
        low = int(f.get('auto_min', 7))
        active = self.active_tile if self.active_tile in self.tile_terms() else self.main_term
        for t in self.tile_terms():
            base = self._zoomed(f.get('size', 12), t)
            size = base if t is active else max(min(low, base), base - drop)
            if size != t.chiral_font:
                t.chiral_font = size
                t.set_font(fonts.desc(family, size))
            if t is self.main_term:
                self.main_font_size = size

    # ---------- terminal columns (Shift+→) ----------
    def add_column(self, folder=None, team=False):
        col = Column(self, self.next_sid, folder or self.focused_folder(), team=team)
        self.next_sid += 1
        self.columns.append(col)
        self.tiles.pack_start(col.frame, True, True, 0)
        col.frame.show_all()
        col.start()
        self.main_term.chiral_font = None
        col.term.grab_focus()
        self._schedule_main_fit()
        self.aware.update_right()
        return col

    def remove_column(self):
        """Shift+←: close the focused column, or the rightmost one when focus is elsewhere."""
        term = self.get_focus()
        col = getattr(term, 'chiral_column', None) if isinstance(term, Vte.Terminal) else None
        if col is None and self.columns:
            col = self.columns[-1]
        if col is None:
            self.toast('no column to close · Shift+→ adds one')
            return
        self.close_column(col)

    def close_column(self, col):
        if col not in self.columns:
            return
        i = self.columns.index(col)
        had_focus = col.term.has_focus()
        self.columns.remove(col)
        self.tiles.remove(col.frame)
        col.frame.destroy()
        if self.active_tile is col.term:
            self.active_tile = None
        if had_focus or self.last_term is col.term:
            (self.columns[i - 1].term if i > 0 else self.main_term).grab_focus()
        self.main_term.chiral_font = None
        self._schedule_main_fit()
        self.aware.update_right()

    def workspace_size(self):
        a = self.overlay.get_allocation()
        return max(a.width, 400), max(a.height, 300)

    def focused_terminal(self):
        f = self.get_focus()
        return f if isinstance(f, Vte.Terminal) else None

    def _on_set_focus(self, _win, widget):
        if widget is None:
            return
        set_lit(self.main_frame, widget is self.main_term)
        for c in self.columns:
            set_lit(c.frame, widget is c.term)
        if isinstance(widget, Vte.Terminal):
            if widget.chiral_sub is None or widget.chiral_sub is not self.preview:
                self.last_term = widget             # a preview is a quick look, not a place to return to
            if widget in self.tile_terms() and widget is not self.active_tile:
                self.active_tile = widget           # the focused column gets the bigger font
                if self.columns:
                    self._fit_tiles()
            self._mark_focused(widget.chiral_sub)
            if widget.chiral_sub:
                self.agents.touch(widget.chiral_sub)
            self.aware.follow(self.cwd_of(widget))
        elif getattr(widget, 'chiral_sub', None) is not None:
            self._mark_focused(widget.chiral_sub)     # the picture in an image window
        else:
            self._mark_focused(None)        # file tree or command bar: no terminal border is lit

    def _mark_focused(self, sub):
        self.focused_sub = sub
        for s in self.subs:
            s.set_focused(s is sub)

    def _restore_focus_if_hidden(self, rev, _pspec):
        if not rev.get_child_revealed() and not rev.get_reveal_child():
            self._focus_back()

    def _focus_back(self):
        t = self.last_term if self.last_term in self.all_terminals() else self.main_term
        if t.chiral_sub and not t.chiral_sub.get_visible():
            t = self.main_term
        t.grab_focus()

    def _keep_panels_on_top(self):
        for w in self.top_layers:
            self.overlay.reorder_overlay(w, -1)

    def term_busy(self, t):
        """True when a program (not the shell prompt) owns the terminal: nano, vim, ..."""
        if t.chiral_is_app:
            return True
        pty = t.get_pty()
        if not pty or not t.chiral_pid:
            return False
        try:
            return os.tcgetpgrp(pty.get_fd()) != t.chiral_pid
        except OSError:
            return False

    # ---------- keys ----------
    def _on_key(self, _w, ev):
        mods = ev.state & MODS
        key = ev.keyval
        focus = self.get_focus()
        term = focus if isinstance(focus, Vte.Terminal) else None

        # inside the tree's preview window: Esc goes back to the tree
        in_sub = term.chiral_sub if term is not None else getattr(focus, 'chiral_sub', None)
        if in_sub is not None and in_sub is self.preview:
            if key == Gdk.KEY_Escape and mods == 0:
                if self.panel_open('tree'):
                    self.tree.view.grab_focus()
                else:
                    self.close_preview()
                    self._focus_back()
                return True

        if key in EDGE_KEYS and mods in (SHIFT, CTRL_SHIFT):
            if mods == SHIFT:
                if isinstance(focus, Gtk.Entry) and key in (Gdk.KEY_Left, Gdk.KEY_Right):
                    return False                      # text selection in the command bar
                if (term and self.cfg['keys'].get('shift_arrows', 'smart') == 'smart'
                        and not term.chiral_keys_first and self.term_busy(term)):
                    return False                      # nano & co. keep Shift+arrows
            if EDGE_KEYS[key] == 'column':
                self.add_column()                 # every Shift+→ adds another column on the right
            elif EDGE_KEYS[key] == 'uncolumn':
                if self.tree.view.has_focus():
                    self.hide_panel('tree')
                else:
                    self.remove_column()          # Shift+← takes one away
            else:
                self.toggle_panel(EDGE_KEYS[key])
            return True

        if mods == CTRL_SHIFT:
            name = Gdk.keyval_name(Gdk.keyval_to_lower(key))
            if name == 't':
                self.new_shell()
                return True
            if name == 'w' and self.focused_sub and (term is self.focused_sub.term
                                                      or focus is self.focused_sub.focus_widget()):
                self.close_sub(self.focused_sub)
                return True
            if name == 'w' and term is not None and term.chiral_column:
                self.close_column(term.chiral_column)
                return True
            if name == 'e':
                self.explain_last()
                return True
            if name == 'f':
                self.toggle_panel('tree')
                return True
            if name == 'b' and term is not None and term.chiral_sub and getattr(term.chiral_sub, 'remote', None):
                term.chiral_sub.remote.buzz()        # ring the person whose terminal this is
                return True

        owner = term.chiral_sub if term is not None else getattr(focus, 'chiral_sub', None)
        if mods == CTRL and key in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab) and owner is not None and owner.tabs is not None:
            imageview.toggle_tab(owner)              # image <-> hex
            return True

        if mods == CTRL and key == Gdk.KEY_o:
            smart = self.cfg['keys'].get('shift_arrows', 'smart') == 'smart'
            if term and smart and not term.chiral_keys_first and self.term_busy(term):
                return False                  # nano's Ctrl+O (save) and friends keep working
            self.toggle_panel('tree')
            return True
            if name == 'c' and term:
                term.copy_clipboard_format(Vte.Format.TEXT)
                return True
            if name == 'v' and term:
                term.paste_clipboard()
                return True

        if mods == CTRL and key in (Gdk.KEY_Left, Gdk.KEY_Right):
            mode = self.cfg['keys'].get('ctrl_arrows', 'smart')
            in_tree = self.tree.view.has_focus()
            if mode != 'off' and not isinstance(focus, Gtk.Entry) and (term or in_tree):
                if not (mode == 'smart' and term and not term.chiral_keys_first and self.term_busy(term)):
                    self.cycle_focus(1 if key == Gdk.KEY_Right else -1)
                    return True

        if mods == CTRL and term and key in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_minus, Gdk.KEY_0):
            self.zoom_terminal(term, {Gdk.KEY_plus: 1, Gdk.KEY_equal: 1, Gdk.KEY_minus: -1, Gdk.KEY_0: 0}[key])
            return True

        if (key == Gdk.KEY_Escape and mods == 0 and not isinstance(focus, Gtk.Entry)
                and (self.panel_open('tree') or self.panel_open('bar'))):
            self.hide_panel('tree')
            self.hide_panel('bar')
            return True

        # window-bar letters (1-9 t h s) only when the bar was opened with Shift+↓, and only once:
        # a bar that appeared because the mouse touched the bottom edge never takes your typing
        if self.panel_open('bar') and 'bar' not in self.hover_open and mods == 0:
            if Gdk.KEY_1 <= key <= Gdk.KEY_9:
                n = key - Gdk.KEY_1
                if n < len(self.subs):
                    self.show_sub(self.subs[n])
                self.hide_panel('bar')
                return True
            if key in (Gdk.KEY_t, Gdk.KEY_h, Gdk.KEY_s):
                {Gdk.KEY_t: self.tile, Gdk.KEY_h: self.hide_all, Gdk.KEY_s: self.show_all_subs}[key]()
                self.hide_panel('bar')
                return True
            if Gdk.keyval_to_unicode(key) or key in (Gdk.KEY_Return, Gdk.KEY_BackSpace, Gdk.KEY_Tab):
                self.hide_panel('bar')                   # anything else: close the bar and type as usual
        return False

    # ---------- panels ----------
    def panel_open(self, name):
        return self.revealers[name].get_reveal_child()

    def toggle_panel(self, name):
        if self.panel_open(name):
            self.hide_panel(name)
        else:
            self.show_panel(name)

    def show_panel(self, name, by_hover=False):
        if name == 'tree':
            self.tree.reveal(self.focused_folder())   # where you are right now, selected
        elif name == 'bar':
            self.bar.rebuild()
        if by_hover:
            self.hover_open.add(name)
        else:
            self.hover_open.discard(name)
        self.revealers[name].set_reveal_child(True)
        self._keep_panels_on_top()
        if by_hover:
            return
        if name == 'tree':
            self.tree.focus()
        elif name == 'cmd':
            self.cmd.open()


    def hide_panel(self, name):
        if not self.panel_open(name):
            return
        self.hover_open.discard(name)
        had_focus = self.revealers[name].get_focus_child() is not None
        self.revealers[name].set_reveal_child(False)
        if name == 'tree':
            in_preview = self.preview is not None and self.preview.term.has_focus()
            self.close_preview()           # a preview you did not keep goes away with the tree
            if in_preview:
                self._focus_back()
        if had_focus or name == 'cmd':
            self._focus_back()

    def _hover(self, name):
        if name == 'tree' and not self.cfg['tree'].get('hover', True):
            return False
        if not self.panel_open(name):
            self.show_panel(name, by_hover=True)
        return False

    def _on_leave(self, _w, ev, name):
        if ev.detail == Gdk.NotifyType.INFERIOR or name not in self.hover_open:
            return False
        self.hide_panel(name)
        return False

    # ---------- sub-terminals ----------
    def sub_number(self, sub):
        return self.subs.index(sub) + 1 if sub in self.subs else len(self.subs) + 1

    def new_sub(self, title, argv=None, cwd=None, app_mode=False, on_exit=None, agent=False, extra_env=None,
                focus=True, geom=None, remote=False, image=None):
        sub = SubWindow(self, self.next_sid, title, app_mode)
        sub.agent = agent
        if agent:
            sub.get_style_context().add_class('agent')
            sub.set_border(3)               # thick enough that the square content fits inside the rounded corners
            sub.set_rounded(9)
        sub.term.chiral_keys_first = agent  # Chiral's keys still work inside an agent
        self.next_sid += 1
        self.subs.append(sub)
        sub.on_exit = on_exit
        area_w, area_h = self.workspace_size()
        n = len([s for s in self.subs if s is not sub and s.get_visible()])
        w, h = int(area_w * 0.55), int(area_h * 0.5)
        sub.place(*(geom or (60 + (n % 6) * 36, 36 + (n % 6) * 30, w, h)))
        sub.term.connect('child-exited', lambda _t, status: self.close_sub(sub, status))
        self.overlay.add_overlay(sub)
        self._keep_panels_on_top()
        sub.show_all()
        sub.update_title()
        sub.cwd = cwd or self.cwd
        sub.remote = None
        if remote:                          # a teammate's terminal: nothing runs here
            sub.get_style_context().add_class('remote')
        else:
            self.spawn(sub.term, role='agent' if agent else 'sub', win=sub.sid, cwd=sub.cwd, argv=argv, extra_env=extra_env)
        if image:
            imageview.add_image_tab(sub, image)       # tabs: image (the picture) and hex
        if focus:
            self.focus_sub(sub)
        else:                               # e.g. the tree's preview: on top, but focus stays where it is
            self.overlay.reorder_overlay(sub, -1)
            self._keep_panels_on_top()
        self._refresh_bar()
        return sub

    def new_shell(self, cwd=None):
        return self.new_sub('bash', cwd=cwd)

    def focus_sub(self, sub, grab=True):
        if sub not in self.subs:
            return
        self.overlay.reorder_overlay(sub, -1)
        self._keep_panels_on_top()
        self._mark_focused(sub)
        target = sub.focus_widget()
        if grab and not target.has_focus():
            target.grab_focus()

    def show_sub(self, sub):
        sub.show()
        self.focus_sub(sub)
        self.hide_panel('bar')

    def hide_sub(self, sub):
        sub.hide()
        if self.focused_sub is sub:
            self._mark_focused(None)
            self.main_term.grab_focus()
        self._refresh_bar()

    def close_sub(self, sub, status=0, refocus=True):
        if sub not in self.subs:
            return
        self.subs.remove(sub)
        self.agents.forget(sub)
        if getattr(sub, 'remote', None):
            sub.remote.close()
        if sub.on_exit:
            cb, sub.on_exit = sub.on_exit, None
            cb(status)
        self.overlay.remove(sub)
        sub.destroy()
        for s in self.subs:
            s.update_title()
        if sub is self.preview:
            self.preview = None
        if refocus and (self.focused_sub is sub or self.focused_sub is None):
            self._mark_focused(None)
            visible = [s for s in self.subs if s.get_visible()]
            (visible[-1].term if visible else self.main_term).grab_focus()
        self._refresh_bar()

    # ---------- the tree's live preview ----------
    def show_preview(self, path, is_dir):
        """One floating window that follows the tree selection: folder → a shell there (listing it),
        binary → hex viewer, text → read-only view. Focus stays in the tree."""
        old = self.preview if self.preview in self.subs else None
        if old:
            geom = (old.x, old.y, old.w, old.h)          # keep where the user put it
        else:
            aw, ah = self.workspace_size()
            geom = (min(320, aw // 3), 28, int(aw * 0.5), int(ah * 0.62))
        name = os.path.basename(path.rstrip('/')) or path
        folder = path if is_dir else os.path.dirname(path)
        env = None
        image = None
        if is_dir:
            argv, env = None, {'CHIRAL_STARTUP': 'ls -la --color=auto'}
        elif os.path.isfile(path) and imageview.is_image(path):
            argv, image = [sys.executable, '-m', 'chiral.hexview', path], path
        elif is_binary(path):
            argv = [sys.executable, '-m', 'chiral.hexview', path]
        else:
            argv = ['less', '-R', '-M', path]
        sub = self.new_sub('preview · %s%s · esc: back' % (name, '/' if is_dir else ''), argv=argv, cwd=folder,
                           app_mode=not is_dir, extra_env=env, focus=False, geom=geom, image=image)
        sub.term.chiral_keys_first = True    # a quick look: Ctrl+O, Shift/Ctrl+arrows always reach Chiral
        sub.preview_path = path
        self.preview = sub
        if old:
            self.close_sub(old, refocus=False)

    def close_preview(self):
        if self.preview in self.subs:
            self.close_sub(self.preview, refocus=False)
        self.preview = None

    def keep_preview(self):
        sub = self.preview
        if sub not in self.subs:
            self.toast('no preview to keep')
            return
        self.preview = None
        sub.term.chiral_keys_first = False   # a normal window now: programs keep their keys again
        sub.title = sub.title.replace('preview · ', '', 1).replace(' · esc: back', '')
        sub.update_title()
        self.toast('kept: ' + sub.title)

    # ---------- team sessions ----------
    def toggle_share(self):
        if self.share.on:
            self.share.stop()
            self.toast('sharing off')
            self.aware.update_share()
            return
        from .session import parse_peers
        from . import sandbox
        scfg = self.cfg.get('sharing', {})
        if not parse_peers(scfg.get('peers', [])):
            self.toast('add people in Settings → Team first')
            self.open_settings('team')
            return
        if scfg.get('mode', 'folder') == 'folder':
            folder = self.focused_folder()
            home = os.path.expanduser('~')
            if not sandbox.available():
                self.toast('bubblewrap (bwrap) is missing: sudo apt install bubblewrap')
                return
            if os.path.realpath(folder) in ('/', os.path.realpath(home)):
                if not self._ask('Share your whole %s?' % ('computer' if folder == '/' else 'home folder'),
                                 'Team members would see <b>everything</b> in <tt>%s</tt>. Usually you '
                                 '<tt>cd</tt> into a project folder first, e.g. <tt>~/work</tt>.'
                                 % GLib.markup_escape_text(folder), ok='Share it anyway'):
                    return
            team = self.share.team_column()
            if team is None or os.path.realpath(team.folder) != os.path.realpath(folder):
                if team is not None:
                    self.close_column(team)
                self.add_column(folder=folder, team=True)
            if self.share.start():
                self.toast('sharing %s · your team gets a locked terminal there, nothing outside it'
                           % folder.replace(home, '~', 1))
        elif self.share.start():
            self.toast('sharing your own terminals (full access)')
        self.aware.update_share()

    def buzzed(self, name):
        """A teammate rang us: shake, flash the borders, bell, a note, and a notification if we are not in front."""
        self.toast('%s is buzzing you' % name)
        try:
            self.get_display().beep()
        except Exception:
            pass
        if not self.is_active():
            self.set_urgency_hint(True)
            GLib.timeout_add(4000, lambda: (self.set_urgency_hint(False), False)[1])
            try:
                note = Gio.Notification.new('Chiral Terminal')
                note.set_body('%s is buzzing you' % name)
                self.app.send_notification('buzz', note)
            except Exception:
                pass
        self.shake()

    def shake(self):
        if getattr(self, '_shaking', False):
            return
        self._shaking = True
        gdk_win = self.get_window()
        state = gdk_win.get_state() if gdk_win else 0
        can_move = not (self.is_maximized() or state & Gdk.WindowState.FULLSCREEN)
        x0, y0 = self.get_position()
        offsets = [10, -10, 8, -8, 6, -6, 4, -4, 2, -2, 0]
        frames = [self.main_frame] + [c.frame for c in self.columns] + list(self.subs)

        def step(i=[0]):
            n = i[0]
            i[0] += 1
            done = n >= len(offsets)
            for f in frames:
                ctx = f.get_style_context()
                (ctx.add_class if (not done and n % 2 == 0) else ctx.remove_class)('buzz')
            if can_move:
                self.move(x0 + (0 if done else offsets[n]), y0)
            if done:
                self._shaking = False
                return False
            return True
        GLib.timeout_add(35, step)

    def open_remote(self, peer_name, ip, port, term_id, title):
        aw, ah = self.workspace_size()
        view = RemoteView(self, peer_name, ip, port, term_id, title)
        view.sub.place(int(aw * 0.1), 30, int(aw * 0.8), int(ah * 0.8))

    def _refresh_bar(self):
        self.aware.update_right()
        if self.panel_open('bar'):
            self.bar.rebuild()

    def tile(self):
        subs = self.subs
        if not subs:
            return
        area_w, area_h = self.workspace_size()
        cols = 1
        while cols * cols < len(subs):
            cols += 1
        rows = (len(subs) + cols - 1) // cols
        cw, ch = area_w // cols, area_h // rows
        for i, s in enumerate(subs):
            s.show()
            s.prev_geom = None
            s.place((i % cols) * cw, (i // cols) * ch, cw, ch)
        self._refresh_bar()

    def hide_all(self):
        for s in self.subs:
            s.hide()
        self._mark_focused(None)
        self.main_term.grab_focus()
        self._refresh_bar()

    def show_all_subs(self):
        for s in self.subs:
            s.show()
        if self.subs:
            self.focus_sub(self.subs[-1])
        self._refresh_bar()

    # ---------- opening things ----------
    def editor_argv(self):
        editor = self.cfg.get('editor') or os.environ.get('CHIRAL_REAL_EDITOR') or ''
        if not editor:
            env_editor = os.environ.get('EDITOR', '')
            editor = env_editor if env_editor and 'chiral-edit' not in env_editor else 'nano'
        return shlex.split(editor)

    def open_file(self, path, hex_view=None):
        path = os.path.abspath(path)
        if os.path.isdir(path):
            self.new_shell(cwd=path)
            return
        name = os.path.basename(path)
        if not hex_view and os.path.isfile(path) and imageview.is_image(path):
            self.new_sub('image ' + name, argv=[sys.executable, '-m', 'chiral.hexview', path],
                         cwd=os.path.dirname(path), app_mode=True, image=path)
            return
        if hex_view or (hex_view is None and os.path.exists(path) and is_binary(path)):
            self.new_sub('hex ' + name, argv=[sys.executable, '-m', 'chiral.hexview', path],
                         cwd=os.path.dirname(path), app_mode=True)
        else:
            argv = self.editor_argv() + [path]
            self.new_sub('%s %s' % (os.path.basename(argv[0]), name), argv=argv,
                         cwd=os.path.dirname(path), app_mode=True)

    def run_float(self, command, cwd=None):
        script = command + '\n__s=$?; printf "\\n\\033[2m[exit %s - Enter closes]\\033[0m" $__s; read _'
        self.new_sub(command[:50], argv=['/bin/bash', '-c', script], cwd=cwd, app_mode=True)

    def popout(self, argv, cwd, on_exit=None):
        title = ' '.join(os.path.basename(a) if i == 0 or '/' in a else a for i, a in enumerate(argv))[:60]
        self.new_sub(title, argv=argv, cwd=cwd, app_mode=True, on_exit=on_exit)

    def nautilus(self, path):
        path = os.path.abspath(path)
        uri = Gio.File.new_for_path(path).get_uri()
        method = 'ShowFolders' if os.path.isdir(path) else 'ShowItems'
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.call_sync('org.freedesktop.FileManager1', '/org/freedesktop/FileManager1',
                          'org.freedesktop.FileManager1', method, GLib.Variant('(ass)', ([uri], '')),
                          None, Gio.DBusCallFlags.NONE, 3000, None)
        except GLib.Error:
            try:
                subprocess.Popen(['nautilus', '--select' if method == 'ShowItems' else '--new-window', path])
            except OSError as e:
                self.toast('could not open Nautilus: %s' % e)
                return
        self.toast('opened in Nautilus: ' + os.path.basename(path))

    # ---------- AI agents ----------
    def focused_folder(self):
        t = self.last_term if self.last_term in self.all_terminals() else self.main_term
        return self.cwd_of(t)

    def new_agent(self, kind=None):
        self.agents.spawn(self.focused_folder(), kind)

    # ---------- top-bar agent icons: install, sign in / set up, or open ----------
    def _ask(self, title, text, ok='Continue'):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.NONE, text=title)
        dlg.format_secondary_markup(text)
        dlg.add_button('Cancel', Gtk.ResponseType.CANCEL)
        dlg.add_button(ok, Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        answer = dlg.run()
        dlg.destroy()
        return answer == Gtk.ResponseType.OK

    def _run_setup(self, title, command, then=None):
        """Run a setup command in a floating terminal through an interactive bash (nvm etc. loaded)."""
        script = ('%s; st=$?; echo; if [ $st -eq 0 ]; then echo "[chiral] done."; else echo "[chiral] failed (exit $st)."; fi; '
                  'printf "Press Enter to close."; read _' % command)
        argv = ['/bin/bash', '--rcfile', self.runtime.rc, '-i', '-c', script]
        sub = self.new_sub(title, argv=argv, cwd=os.path.expanduser('~'), app_mode=True,
                           on_exit=lambda _st: GLib.timeout_add(300, lambda: (then() if then else None, False)[1]))
        aw, ah = self.workspace_size()
        sub.place(int(aw * 0.2), 40, int(aw * 0.6), int(ah * 0.55))

    def agent_chip_clicked(self, kind):
        from . import agent_status as ast
        chip = self.aware.agent_chips.chips[kind]
        spec = ast.SPECS[kind]
        phase = chip.phase()
        refresh = lambda: self.aware.agent_chips.refresh(find_tools=True)
        if phase == 'unknown':
            self.toast('checking %s…' % spec['label'])
            return
        if phase == 'ready':
            if kind == 'local':
                self.cfg['claude']['local_model'] = chip.state.get('model', '')
            self.new_agent(kind)
            return
        if phase == 'missing':
            if self._ask('%s is not installed. Install it now?' % ('Ollama (Local AI)' if kind == 'local' else spec['label']),
                         'Chiral will run this in a floating terminal, where you can watch it'
                         '%s:\n\n<tt>%s</tt>' % (' and type your password' if kind == 'local' else '',
                                                   GLib.markup_escape_text(spec['install'])), ok='Install'):
                self._run_setup('install %s' % spec['label'].lower(), spec['install'], then=refresh)
            return
        # installed but not ready
        if kind != 'local':
            if self._ask('Sign in to %s?' % spec['label'],
                         '%s\nChiral runs <tt>%s</tt> in a floating terminal. Once you are signed in, %s is ready '
                         'to use as an AI agent.' % (spec['login_note'], spec['login'], spec['label']), ok='Sign in'):
                self._run_setup('sign in: %s' % spec['label'].lower(), spec['login'], then=refresh)
            return
        self._setup_local(chip.state, refresh)

    def _setup_local(self, state, refresh):
        from . import agent_status as ast
        tool = (self.aware.agent_chips.tools or {}).get('ollama') or 'ollama'
        if not state.get('server'):
            if not self._ask('Start the Local AI server?', 'Chiral starts <tt>ollama serve</tt> in the background. '
                             'It keeps running until you log out.', ok='Start'):
                return
            try:
                subprocess.Popen([tool, 'serve'], start_new_session=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                self.toast('could not start ollama: %s' % e)
                return
            self.toast('starting the Local AI server…')
            GLib.timeout_add(2500, lambda: (refresh(), False)[1])
            if state.get('models'):
                return
        model = self._choose_model(ast.LOCAL_MODELS)
        if not model:
            return

        def done():
            self.cfg['claude']['local_model'] = model
            try:
                self.last_saved_settings = config.save(self.cfg)
            except OSError:
                pass
            refresh()
        self._run_setup('download %s' % model, '%s pull %s' % (shlex.quote(tool), shlex.quote(model)), then=done)

    def _choose_model(self, models):
        dlg = Gtk.Dialog(title='Choose a local model', transient_for=self, modal=True)
        dlg.add_button('Cancel', Gtk.ResponseType.CANCEL)
        dlg.add_button('Download', Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_spacing(8)
        for side in ('start', 'end', 'top', 'bottom'):
            getattr(box, 'set_margin_' + side)(14)
        box.pack_start(Gtk.Label(label='Pick a model to download and run on this computer.', xalign=0), False, False, 0)
        combo = Gtk.ComboBoxText.new_with_entry()
        for name, desc in models:
            combo.append(name, desc)
        combo.set_active(0)
        box.pack_start(combo, False, False, 0)
        hint = Gtk.Label(label='Or type any model name from ollama.com/library.', xalign=0)
        hint.get_style_context().add_class('dim-label')
        box.pack_start(hint, False, False, 0)
        dlg.show_all()
        answer = dlg.run()
        name = combo.get_active_id() or combo.get_child().get_text().split(' ')[0].strip()
        dlg.destroy()
        return name if answer == Gtk.ResponseType.OK and name else None

    def ask_claude(self, text):
        self.agents.send(text)

    def explain_last(self):
        self.agents.explain()

    def _terminal_for_win(self, win_id):
        if win_id == 0:
            return self.main_term, 'the main terminal'
        for c in self.columns:
            if c.sid == win_id:
                return c.term, 'column %d' % c.number()
        for s in self.subs:
            if s.sid == win_id:
                return s.term, 'window %d (%s)' % (self.sub_number(s), s.title)
        return None, 'a closed window'

    def _snapshot(self, term):
        try:
            _col, row = term.get_cursor_position()
            start = max(0, row - CONTEXT_LINES)
            text = term.get_text_range(start, 0, row, term.get_column_count(), None, None)[0]
        except (TypeError, GLib.Error):
            text = term.get_text(None, None)[0] if term else ''
        lines = [l.rstrip() for l in (text or '').splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        return '\n'.join(lines[-CONTEXT_LINES:])

    @staticmethod
    def live_cwd(term):
        """The folder the terminal's shell is in right now, straight from the system."""
        try:
            return os.readlink('/proc/%d/cwd' % term.chiral_pid) if term.chiral_pid else None
        except OSError:
            return None

    def cwd_of(self, term):
        live = self.live_cwd(term)
        if live and os.path.isdir(live):
            return live
        return term.chiral_sub.cwd if term.chiral_sub else self.cwd

    def _poll_events(self):
        events = self.runtime.read_events()
        for win_id, status, cwd, command in events:
            if win_id == 0 and os.path.isdir(cwd):
                self.cwd = cwd
            for s in self.subs:
                if s.sid == win_id and os.path.isdir(cwd):
                    s.cwd = cwd
            term, label = self._terminal_for_win(win_id)
            output = self._snapshot(term) if term and status != 0 else ''
            entry = '## %s: `%s` → exit %d (in %s)\n' % (label, command, status, cwd)
            if output:
                entry += '```\n%s\n```\n' % output
            self.context = (self.context + [entry])[-CONTEXT_ENTRIES:]
            try:
                with open(self.runtime.context, 'w') as f:
                    f.write('# Recent terminal activity (newest last)\n\n' + '\n'.join(self.context))
            except OSError:
                pass
            self.agents.on_command(label, status, command)
        if events:                          # a command finished: folder or git state may have changed
            t = self.last_term if self.last_term in self.all_terminals() else self.main_term
            self.aware.follow(self.cwd_of(t))
            self.aware.refresh()
        return True

    # ---------- command bar entries ----------
    def commands(self):
        cmds = [
            ('AI agent', self.new_agent),              # the default agent in a floating window, watching your terminals
            ('AI agent: claude', lambda: self.new_agent('claude')),
            ('AI agent: codex', lambda: self.new_agent('codex')),
            ('AI agent: local (ollama)', lambda: self.new_agent('local')),
            ('new terminal window', self.new_shell),
            ('new terminal column (Shift+→)', self.add_column),
            ('file tree (Ctrl+Shift+F)', lambda: self.show_panel('tree')),
            ('close a terminal column (Shift+←)', self.remove_column),
            ('windows', lambda: self.show_panel('bar')),
            ('explain last failure (AI agent)', self.explain_last),
            ('settings', self.open_settings),
            ('settings: appearance (themes, accent, strands)', lambda: self.open_settings('appearance')),
            ('settings: font', lambda: self.open_settings('font')),
            ('settings: behavior', lambda: self.open_settings('behavior')),
            ('settings: AI agents', lambda: self.open_settings('agents')),
            ('settings: keys', lambda: self.open_settings('keys')),
            ('settings file (text)', self.open_settings_file),
            ('tile windows', self.tile),
            ('hide all windows', self.hide_all),
            ('show all windows', self.show_all_subs),
            ('open folder in nautilus', lambda: self.nautilus(self.cwd)),
            ('awareness bar: show / hide', lambda: self.set_flag('awareness', not self.cfg.get('awareness', True))),
            ('hex view of a file…', lambda: (self.show_panel('tree'), self.toast('select a file, press x'))),
        ]
        for name in ('strands', 'off'):
            cmds.append(('background: ' + name, lambda n=name: self.set_setting('background', n)))
        for name in themes.ANIMATION_MS:
            cmds.append(('animations: ' + name, lambda n=name: self.set_setting('animations', n)))
        return cmds

    # ---------- focus ring ----------
    def focus_ring(self):
        """Everything Ctrl+←/→ can reach, left to right: tree, main, floating windows, columns."""
        ring = []
        if self.panel_open('tree'):
            ring.append(('tree', 'file tree'))
        ring.append((self.main_term, 'main terminal'))
        for s in self.subs:
            if s.get_visible():
                ring.append((s.focus_widget(), '%d  %s' % (self.sub_number(s), s.title)))
        for c in self.columns:
            ring.append((c.term, 'column %d' % c.number()))
        return ring

    def cycle_focus(self, step):
        ring = self.focus_ring()
        focus = self.get_focus()
        current = 0
        for i, (target, _name) in enumerate(ring):
            if target is focus or (target == 'tree' and self.tree.view.has_focus()):
                current = i
                break
        target, name = ring[(current + step) % len(ring)]
        if target == 'tree':
            self.hover_open.discard('tree')          # keyboard focus keeps it open
            self.tree.focus()
        elif target.chiral_sub:
            self.focus_sub(target.chiral_sub)
        else:
            target.grab_focus()
        if len(ring) > 1:
            self.toast_widget.show_text(name, seconds=0.9)
            self._keep_panels_on_top()

    def toast(self, text):
        self.toast_widget.show_text(text)
        self._keep_panels_on_top()
