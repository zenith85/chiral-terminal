"""Shift+↓ window bar, Shift+↑ command bar, and a small toast for messages."""
import os
import time

from gi.repository import GLib, Gdk, Gtk

FILE_SKIP = {'.git', '__pycache__', 'node_modules', '.venv', '.mypy_cache', '.pytest_cache'}
MAX_FILES = 20000
MAX_ROWS = 9


class WindowBar(Gtk.EventBox):
    """Every sub-terminal, hidden ones too. Click or press 1-9 to bring one back."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.get_style_context().add_class('chiral-panel')
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)
        outer.pack_start(Gtk.Separator(), False, False, 0)
        self.row = Gtk.Box(spacing=2)
        self.row.get_style_context().add_class('chiral-bar')
        self.row.set_margin_start(6)
        self.row.set_margin_end(6)
        self.row.set_margin_top(3)
        self.row.set_margin_bottom(3)
        outer.pack_start(self.row, False, False, 0)

    def rebuild(self):
        for child in self.row.get_children():
            self.row.remove(child)
        title = Gtk.Label(label='windows ')
        title.get_style_context().add_class('chiral-dim')
        self.row.pack_start(title, False, False, 0)
        subs = self.win.subs
        if not subs:
            empty = Gtk.Label(label='none yet · Ctrl+Shift+T opens one')
            empty.get_style_context().add_class('chiral-dim')
            self.row.pack_start(empty, False, False, 0)
        for i, sub in enumerate(subs):
            text = ' %d %s%s ' % (i + 1, sub.title, '' if sub.get_visible() else ' (hidden)')
            b = Gtk.Button(label=text)
            b.set_can_focus(False)
            ctx = b.get_style_context()
            if sub is self.win.focused_sub and sub.get_visible():
                ctx.add_class('focused')
            if not sub.get_visible():
                ctx.add_class('hidden-win')
            b.connect('clicked', lambda _b, s=sub: self.win.show_sub(s))
            self.row.pack_start(b, False, False, 0)
        spacer = Gtk.Label()
        self.row.pack_start(spacer, True, True, 0)
        for text, cb in (('t tile', self.win.tile), ('h hide all', self.win.hide_all),
                         ('s show all', self.win.show_all_subs)):
            b = Gtk.Button(label=text)
            b.set_can_focus(False)
            b.connect('clicked', lambda _b, f=cb: f())
            self.row.pack_start(b, False, False, 0)
        hint = Gtk.Label(label='  1-9 jump · shift+↓ hide')
        hint.get_style_context().add_class('chiral-dim')
        self.row.pack_start(hint, False, False, 0)
        self.row.show_all()


class CommandBar(Gtk.EventBox):
    """One line that runs anything: commands, @files, #ask claude, window numbers, shell commands."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.get_style_context().add_class('chiral-panel')
        self._files = []
        self._files_root = None
        self._files_time = 0
        self._items = []

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.get_style_context().add_class('chiral-cmd')
        self.add(box)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text('command · @file · #ask the AI agent · 1-9 window · or a shell command')
        self.entry.set_width_chars(1)
        self.entry.connect('changed', lambda *_: self._refresh())
        self.entry.connect('key-press-event', self._on_key)
        self.entry.connect('activate', lambda *_: self._run_selected())
        box.pack_start(self.entry, False, False, 0)
        self.list = Gtk.ListBox()
        self.list.get_style_context().add_class('chiral-list')
        self.list.set_activate_on_single_click(True)
        self.list.connect('row-activated', lambda _l, row: self._run(row.get_index()))
        box.pack_start(self.list, False, False, 0)

    # --- fixed width, whatever the content asks for ---
    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.CONSTANT_SIZE

    def do_get_preferred_width(self):
        w = self.panel_width()
        return w, w

    def do_get_preferred_width_for_height(self, _h):
        return self.do_get_preferred_width()

    def do_get_preferred_height_for_width(self, _w):
        return self.do_get_preferred_height()

    def panel_width(self):
        return max(300, min(720, self.win.workspace_size()[0] - 40))

    def open(self):
        self.entry.set_text('')
        self._refresh()
        self.entry.grab_focus()

    # --- sources ---
    def _project_files(self):
        root = self.win.cwd
        if root == self._files_root and time.time() - self._files_time < 15:
            return self._files
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in FILE_SKIP and not d.startswith('.')]
            for f in filenames:
                files.append(os.path.relpath(os.path.join(dirpath, f), root))
                if len(files) >= MAX_FILES:
                    break
            if len(files) >= MAX_FILES:
                break
        self._files, self._files_root, self._files_time = files, root, time.time()
        return files

    @staticmethod
    def _score(query, text):
        """Lower is better; None means no match. Substring beats subsequence."""
        q, t = query.lower(), text.lower()
        if not q:
            return 0
        i = t.find(q)
        if i >= 0:
            return i + (0 if t.endswith(q) or '/' + q in t else 50)
        pos, gaps = -1, 0
        for ch in q:
            nxt = t.find(ch, pos + 1)
            if nxt < 0:
                return None
            gaps += nxt - pos - 1
            pos = nxt
        return 200 + gaps

    def _match(self, query, pairs):
        scored = []
        for label, data in pairs:
            s = self._score(query, label)
            if s is not None:
                scored.append((s, len(label), label, data))
        scored.sort(key=lambda x: (x[0], x[1]))
        return [(label, data) for _, _, label, data in scored]

    def _build(self, text):
        q = text.strip()
        items = []
        if q.startswith('@'):
            for rel, _ in self._match(q[1:], [(f, None) for f in self._project_files()])[:MAX_ROWS]:
                items.append(('@', rel, lambda r=rel: self.win.open_file(os.path.join(self.win.cwd, r))))
            return items
        if q.startswith('#'):
            ask = q[1:].strip()
            items.append(('#', 'ask the AI agent: ' + (ask or '…'), lambda a=ask: self.win.ask_claude(a) if a else None))
            return items
        if q.isdigit():
            n = int(q)
            if 1 <= n <= len(self.win.subs):
                sub = self.win.subs[n - 1]
                items.append(('>', 'go to window %d: %s' % (n, sub.title), lambda s=sub: self.win.show_sub(s)))
        commands = self.win.commands()
        cq = q[1:] if q.startswith('>') else q
        for label, fn in self._match(cq, commands)[:MAX_ROWS]:
            items.append(('>', label, fn))
        if q and not q.startswith('>'):
            for rel, _ in self._match(q, [(f, None) for f in self._project_files()])[:3]:
                items.append(('@', rel, lambda r=rel: self.win.open_file(os.path.join(self.win.cwd, r))))
            items.append(('$', 'run in a new window: ' + q, lambda c=q: self.win.run_float(c)))
        return items[:MAX_ROWS]

    def _refresh(self):
        self._items = self._build(self.entry.get_text())
        for row in self.list.get_children():
            self.list.remove(row)
        for tag, label, _ in self._items:
            lbl = Gtk.Label(xalign=0)
            lbl.set_markup('<b>%s</b>  %s' % (GLib.markup_escape_text(tag), GLib.markup_escape_text(label)))
            lbl.set_margin_start(8)
            lbl.set_margin_top(2)
            lbl.set_margin_bottom(2)
            self.list.add(lbl)
        self.list.show_all()
        first = self.list.get_row_at_index(0)
        if first:
            self.list.select_row(first)

    def _selected_index(self):
        row = self.list.get_selected_row()
        return row.get_index() if row else 0

    def _on_key(self, _entry, ev):
        key = ev.keyval
        if key == Gdk.KEY_Escape:
            self.win.hide_panel('cmd')
            return True
        if key in (Gdk.KEY_Down, Gdk.KEY_Up, Gdk.KEY_Tab):
            if ev.state & Gdk.ModifierType.SHIFT_MASK and key != Gdk.KEY_Tab:
                return False          # Shift+↑ closes the bar (window handler)
            n = len(self._items)
            if n:
                step = -1 if key == Gdk.KEY_Up else 1
                i = (self._selected_index() + step) % n
                self.list.select_row(self.list.get_row_at_index(i))
            return True
        return False

    def _run_selected(self):
        self._run(self._selected_index())

    def _run(self, index):
        if not self._items:
            return
        _tag, _label, fn = self._items[min(index, len(self._items) - 1)]
        self.win.hide_panel('cmd')
        if fn:
            GLib.idle_add(lambda: (fn(), False)[1])


class Toast(Gtk.Revealer):
    def __init__(self):
        super().__init__()
        self.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self.set_halign(Gtk.Align.END)
        self.set_valign(Gtk.Align.START)
        self.set_margin_top(8)
        self.set_margin_end(8)
        box = Gtk.EventBox()
        box.get_style_context().add_class('chiral-toast')
        self.label = Gtk.Label()
        self.label.set_margin_start(10)
        self.label.set_margin_end(10)
        self.label.set_margin_top(4)
        self.label.set_margin_bottom(4)
        box.add(self.label)
        self.add(box)
        self._source = 0

    def show_text(self, text, seconds=3):
        self.label.set_text(text)
        self.set_reveal_child(True)
        if self._source:
            GLib.source_remove(self._source)
        self._source = GLib.timeout_add(int(seconds * 1000), self._hide)

    def _hide(self):
        self._source = 0
        self.set_reveal_child(False)
        return False
