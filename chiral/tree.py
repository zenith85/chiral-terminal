"""Ctrl+O file tree. Takes its own space on the left; also appears when the mouse touches the left edge.

Moving through it with the keys shows a live preview window: a folder as a shell in that folder, a
binary in the hex viewer, a text file read-only. Space keeps the preview; Enter opens a file for real
and opens / closes a folder in the tree."""
import os
import shutil
import subprocess
import threading
from urllib.parse import unquote, urlparse

from gi.repository import GLib, Gdk, Gtk

PREVIEW_DELAY_MS = 250

SKIP = {'.git', '__pycache__', 'node_modules', '.venv', '.mypy_cache', '.pytest_cache'}
PLACEHOLDER = ''           # a folder's first child until it is opened: empty name and path


class FileTree(Gtk.EventBox):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.root = None
        self.modified = set()
        self.get_style_context().add_class('chiral-panel')

        outer = Gtk.Box()
        self.add(outer)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.pack_start(box, True, True, 0)
        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        self.header = Gtk.Label(xalign=0)
        self.header.get_style_context().add_class('chiral-dim')
        self.header.set_ellipsize(1)      # start: keep the end of long paths
        self.header.set_max_width_chars(1)
        self.header.set_margin_start(8)
        self.header.set_margin_top(4)
        self.header.set_margin_bottom(4)
        box.pack_start(self.header, False, False, 0)

        # name, path, is_dir, markup
        self.store = Gtk.TreeStore(str, str, bool, str)
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_headers_visible(False)
        self.view.set_show_expanders(False)
        self.view.set_level_indentation(14)
        self.view.set_enable_search(True)
        self.view.set_search_column(0)
        self.view.set_activate_on_single_click(True)
        self.view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)   # Ctrl+click picks several
        self.clip = None                 # ('copy' | 'cut', [paths]) from Ctrl+C / Ctrl+X
        col = Gtk.TreeViewColumn('name', Gtk.CellRendererText(), markup=3)
        self.view.append_column(col)
        self.view.connect('test-expand-row', self._on_expand)
        self.view.connect('row-expanded', lambda _v, it, _p: self._set_arrow(it, True))
        self.view.connect('row-collapsed', lambda _v, it, _p: self._set_arrow(it, False))
        self.view.connect('row-activated', self._on_activate)
        self.view.connect('key-press-event', self._on_key)
        self.view.connect('cursor-changed', lambda *_: self._schedule_preview())
        self._preview_source = 0
        self._quiet = False           # cursor moves made by Chiral itself: no preview
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.view)
        box.pack_start(scroll, True, True, 0)

        # rename line (F2): appears at the bottom, Enter renames, Esc cancels
        self.rename_bar = Gtk.Revealer()
        rbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for side in ('start', 'end', 'top'):
            getattr(rbox, 'set_margin_' + side)(6)
        self.rename_label = Gtk.Label(xalign=0)
        self.rename_label.get_style_context().add_class('chiral-dim')
        self.rename_entry = Gtk.Entry()
        self.rename_entry.connect('activate', lambda *_: self._finish_rename())
        self.rename_entry.connect('key-press-event', self._rename_key)
        rbox.pack_start(self.rename_label, False, False, 0)
        rbox.pack_start(self.rename_entry, False, False, 0)
        self.rename_bar.add(rbox)
        box.pack_start(self.rename_bar, False, False, 0)
        self._renaming = None

        self.clip_label = Gtk.Label(xalign=0)
        self.clip_label.get_style_context().add_class('chiral-accent')
        self.clip_label.set_margin_start(8)
        self.clip_label.set_ellipsize(3)
        self.clip_label.set_max_width_chars(1)
        box.pack_start(self.clip_label, False, False, 0)

        hint = Gtk.Label(xalign=0)
        hint.set_markup('↑↓ preview · → / ← folder\nenter open · space lock preview\nctrl+c / x / v copy cut paste\nf2 rename · x hex · o nautilus\nt shell · r refresh · ctrl+o close')
        hint.get_style_context().add_class('chiral-dim')
        hint.set_margin_start(8)
        hint.set_margin_top(4)
        hint.set_margin_bottom(6)
        box.pack_start(hint, False, False, 0)

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
        return 300

    # --- content ---
    def refresh(self, root):
        root = os.path.abspath(root)
        expanded = []
        if root == self.root:
            self.view.map_expanded_rows(lambda _v, path, _d: expanded.append(self.store[path][1]), None)
        self.root = root
        self.header.set_text(root.replace(os.path.expanduser('~'), '~', 1))
        self.modified = self._git_modified(root)
        self.store.clear()
        self._fill(None, root)
        for folder in expanded:           # parents come before children, so each lookup finds its row
            path = self._find(folder)
            if path is not None:
                self.view.expand_row(path, False)

    def _find(self, full, it=None):
        it = self.store.iter_children(it)
        while it is not None:
            p = self.store[it][1]
            if p == full:
                return self.store.get_path(it)
            if self.store[it][2] and full.startswith(p + os.sep) and self.view.row_expanded(self.store.get_path(it)):
                return self._find(full, it)
            it = self.store.iter_next(it)
        return None

    def reveal(self, folder):
        """Show `folder` inside its parent, opened and selected, so the tree starts where you are."""
        folder = os.path.abspath(folder)
        parent = os.path.dirname(folder) if folder != os.sep else folder
        self.refresh(parent)
        path = self._find(folder) if parent != folder else None
        if path is None:
            return
        self._quiet = True                  # placing the cursor ourselves: no preview
        self.view.expand_row(path, False)
        self.view.set_cursor(path, None, False)
        self.view.scroll_to_cell(path, None, True, 0.2, 0)
        self._quiet = False

    def _git_modified(self, root):
        try:
            top = subprocess.run(['git', '-C', root, 'rev-parse', '--show-toplevel'], capture_output=True,
                                 text=True, timeout=1).stdout.strip()
            if not top:
                return set()
            out = subprocess.run(['git', '-C', top, 'status', '--porcelain'], capture_output=True, text=True,
                                 timeout=1).stdout
        except (OSError, subprocess.SubprocessError):
            return set()
        changed = set()
        for line in out.splitlines():
            path = line[3:].split(' -> ')[-1].strip('"')
            full = os.path.join(top, path)
            changed.add(full.rstrip('/'))
            parent = os.path.dirname(full)
            while parent.startswith(top) and parent not in changed:
                changed.add(parent)
                parent = os.path.dirname(parent)
        return changed

    def _fill(self, parent, path):
        show_hidden = self.win.cfg['tree'].get('show_hidden', False)
        try:
            names = os.listdir(path)
        except OSError:
            return
        entries = []
        for n in names:
            if n in SKIP or (n.startswith('.') and not show_hidden):
                continue
            full = os.path.join(path, n)
            entries.append((not os.path.isdir(full), n.lower(), n, full))
        for is_file, _, name, full in sorted(entries):
            is_dir = not is_file
            it = self.store.append(parent, [name, full, is_dir, self._markup(name, full, is_dir)])
            if is_dir:
                self.store.append(it, [PLACEHOLDER, PLACEHOLDER, False, ''])

    def _markup(self, name, full, is_dir):
        theme = self.win.theme
        name_e = GLib.markup_escape_text(name)
        if is_dir:
            text = '<span foreground="%s">▸ %s/</span>' % (theme['palette'][4], name_e)
        elif os.access(full, os.X_OK):
            text = '  <span foreground="%s">%s*</span>' % (theme['palette'][2], name_e)
        else:
            text = '  ' + name_e
        if full in self.modified:
            text += '  <span foreground="%s">M</span>' % theme['palette'][1]
        return text

    def _set_arrow(self, it, is_open):
        row = self.store[it]
        if row[2]:
            row[3] = row[3].replace('▾ ' if not is_open else '▸ ', '▸ ' if not is_open else '▾ ', 1)

    def _on_expand(self, _view, it, _path):
        child = self.store.iter_children(it)
        if child is not None and self.store[child][1] == PLACEHOLDER:
            self.store.remove(child)
            self._fill(it, self.store[it][1])
        return False

    # --- actions ---
    def _selected(self):
        """The item under the cursor (the one the preview and single-item keys act on)."""
        path, _col = self.view.get_cursor()
        if path is None:
            return None, False
        row = self.store[path]
        return (row[1], row[2]) if row[1] != PLACEHOLDER else (None, False)

    def _selected_paths(self):
        model, paths = self.view.get_selection().get_selected_rows()
        out = [model[p][1] for p in paths if model[p][1] != PLACEHOLDER]
        if not out:
            full, _ = self._selected()
            out = [full] if full else []
        return out

    # --- copy / cut / paste / rename ---
    def _copy(self, mode):
        paths = self._selected_paths()
        if not paths:
            return
        self.clip = (mode, paths)
        names = ', '.join(os.path.basename(p) for p in paths[:3]) + (' …' if len(paths) > 3 else '')
        self.clip_label.set_text('%s: %s  (ctrl+v pastes)' % ('cut' if mode == 'cut' else 'copied', names))
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text('\n'.join(paths), -1)   # paths, for pasting in a shell
        self.win.toast('%s %d item%s' % ('cut' if mode == 'cut' else 'copied', len(paths), '' if len(paths) == 1 else 's'))

    def _clipboard_files(self):
        """Files copied or cut in Nautilus (x-special/gnome-copied-files), if any."""
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        data = clip.wait_for_contents(Gdk.Atom.intern('x-special/gnome-copied-files', False))
        if data is None or data.get_length() <= 0:
            return None
        lines = data.get_data().decode('utf-8', 'ignore').splitlines()
        if not lines or lines[0] not in ('copy', 'cut'):
            return None
        paths = [unquote(urlparse(u).path) for u in lines[1:] if u.startswith('file://')]
        return (lines[0], paths) if paths else None

    def _paste_target(self):
        full, is_dir = self._selected()
        if not full:
            return self.root
        return full if is_dir else os.path.dirname(full)

    @staticmethod
    def _free_name(folder, name):
        target = os.path.join(folder, name)
        if not os.path.lexists(target):
            return target
        stem, ext = os.path.splitext(name) if not os.path.isdir(target) else (name, '')
        n = 1
        while True:
            candidate = os.path.join(folder, '%s (copy%s)%s' % (stem, '' if n == 1 else ' %d' % n, ext))
            if not os.path.lexists(candidate):
                return candidate
            n += 1

    def _paste(self):
        source = self._clipboard_files() or self.clip
        if not source:
            self.win.toast('nothing to paste · ctrl+c or ctrl+x first')
            return
        mode, paths = source
        dest = self._paste_target()
        if not dest or not os.path.isdir(dest):
            return

        def work():
            done, errors, last = 0, [], None
            for src in paths:
                try:
                    if mode == 'cut' and os.path.abspath(dest).startswith(os.path.abspath(src) + os.sep):
                        raise OSError('cannot move a folder into itself')
                    if mode == 'cut' and os.path.dirname(os.path.abspath(src)) == os.path.abspath(dest):
                        continue                                   # already there
                    target = self._free_name(dest, os.path.basename(src.rstrip(os.sep)))
                    if mode == 'cut':
                        shutil.move(src, target)
                    elif os.path.isdir(src) and not os.path.islink(src):
                        shutil.copytree(src, target, symlinks=True)
                    else:
                        shutil.copy2(src, target, follow_symlinks=False)
                    done, last = done + 1, target
                except (OSError, shutil.Error) as e:
                    errors.append('%s: %s' % (os.path.basename(src), e))
            GLib.idle_add(self._paste_done, mode, done, errors, dest, last)
        self.win.toast('%s %d item%s…' % ('moving' if mode == 'cut' else 'copying', len(paths), '' if len(paths) == 1 else 's'))
        threading.Thread(target=work, daemon=True).start()

    def _paste_done(self, mode, done, errors, dest, last):
        if mode == 'cut' and self.clip and self.clip[0] == 'cut':
            self.clip = None                                     # moved: the cut is used up
            self.clip_label.set_text('')
        self.refresh(self.root)
        folder = self._find(dest)
        if folder is not None:
            self._quiet = True
            self.view.expand_row(folder, False)
            self._quiet = False
        if last:
            self._reveal_path(last)
        verb = 'moved' if mode == 'cut' else 'copied'
        self.win.toast('%s %d item%s%s' % (verb, done, '' if done == 1 else 's',
                                             (' · %d failed: %s' % (len(errors), errors[0])) if errors else ''))
        return False

    def _reveal_path(self, full):
        path = self._find(full)
        if path is not None:
            self._quiet = True
            self.view.set_cursor(path, None, False)
            self.view.scroll_to_cell(path, None, True, 0.3, 0)
            self._quiet = False

    def _start_rename(self):
        full, _ = self._selected()
        if not full:
            return
        self._renaming = full
        name = os.path.basename(full.rstrip(os.sep))
        self.rename_label.set_text('rename %s  (enter: ok · esc: cancel)' % name)
        self.rename_entry.set_text(name)
        self.rename_bar.set_reveal_child(True)
        self.rename_entry.grab_focus()
        stem = os.path.splitext(name)[0] if not os.path.isdir(full) and '.' in name[1:] else name
        self.rename_entry.select_region(0, len(stem))           # the name, not the extension

    def _rename_key(self, _entry, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self._end_rename()
            return True
        return False

    def _end_rename(self):
        self._renaming = None
        self.rename_bar.set_reveal_child(False)
        self.view.grab_focus()

    def _finish_rename(self):
        src = self._renaming
        new = self.rename_entry.get_text().strip()
        if not src or not new or new == os.path.basename(src):
            self._end_rename()
            return
        if '/' in new or new in ('.', '..'):
            self.win.toast('a name cannot contain "/"')
            return
        target = os.path.join(os.path.dirname(src), new)
        if os.path.lexists(target):
            self.win.toast('"%s" already exists here' % new)
            return
        try:
            os.rename(src, target)
        except OSError as e:
            self.win.toast('could not rename: %s' % e)
            return
        self._end_rename()
        self.refresh(self.root)
        self._reveal_path(target)
        self.win.toast('renamed to ' + new)

    def _on_activate(self, view, path, _col):
        full, is_dir = self.store[path][1], self.store[path][2]
        if is_dir:
            if view.row_expanded(path):
                view.collapse_row(path)
            else:
                view.expand_row(path, False)
            return
        self.win.hide_panel('tree')
        self.win.open_file(full)

    def _on_key(self, _view, ev):
        if ev.state & Gdk.ModifierType.CONTROL_MASK and not ev.state & (Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.SHIFT_MASK):
            name = Gdk.keyval_name(Gdk.keyval_to_lower(ev.keyval))
            if name in ('c', 'x'):
                self._copy('copy' if name == 'c' else 'cut')
                return True
            if name == 'v':
                self._paste()
                return True
            return False
        if ev.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK):
            return False
        if ev.keyval == Gdk.KEY_F2:
            self._start_rename()
            return True
        if ev.state & Gdk.ModifierType.SHIFT_MASK:
            return False
        if ev.keyval in (Gdk.KEY_Right, Gdk.KEY_Left, Gdk.KEY_l, Gdk.KEY_h):
            return self._arrow(ev.keyval in (Gdk.KEY_Right, Gdk.KEY_l))
        full, is_dir = self._selected()
        key = Gdk.keyval_name(ev.keyval)
        if key == 'r':
            self.refresh(self.root or self.win.cwd)
            return True
        if key == 'space':
            self.win.keep_preview()
            return True
        if not full:
            return False
        if key == 'x' and not is_dir:
            self.win.hide_panel('tree')
            self.win.open_file(full, hex_view=True)
            return True
        if key == 'o':
            self.win.nautilus(full)
            return True
        if key == 't':
            self.win.hide_panel('tree')
            self.win.new_shell(cwd=full if is_dir else os.path.dirname(full))
            return True
        return False

    def _arrow(self, right):
        path, _col = self.view.get_cursor()
        if path is None:
            return False
        it = self.store.get_iter(path)
        is_dir = self.store[it][2]
        if right:
            if is_dir and not self.view.row_expanded(path):
                self.view.expand_row(path, False)
            elif is_dir and self.store.iter_n_children(it):
                self.view.set_cursor(self.store.get_path(self.store.iter_children(it)), None, False)
            return True
        if is_dir and self.view.row_expanded(path):
            self.view.collapse_row(path)
        else:
            parent = self.store.iter_parent(it)
            if parent is not None:
                self.view.set_cursor(self.store.get_path(parent), None, False)
        return True

    def focus(self):
        self.view.grab_focus()
        if self.view.get_cursor()[0] is None and len(self.store):
            self._quiet = True
            self.view.set_cursor(Gtk.TreePath.new_first(), None, False)
            self._quiet = False

    # --- live preview ---
    def _schedule_preview(self):
        if self._quiet or not self.win.cfg['tree'].get('preview', True) or not self.view.has_focus():
            return
        if self._preview_source:
            GLib.source_remove(self._preview_source)
        self._preview_source = GLib.timeout_add(PREVIEW_DELAY_MS, self._do_preview)

    def _do_preview(self):
        self._preview_source = 0
        if not self.win.panel_open('tree'):
            return False
        full, is_dir = self._selected()
        current = self.win.preview
        if full and not (current in self.win.subs and getattr(current, 'preview_path', None) == full):
            self.win.show_preview(full, is_dir)
        return False
