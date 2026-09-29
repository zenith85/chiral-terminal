"""The settings window (Shift+↑ → settings, or settings: appearance / font / ... · `chiral settings`).

Every change applies immediately and is saved to ~/.config/chiral/chiral.toml a moment later, so the
file and the window always agree. Themes are shown as small live previews.
"""
import copy
import math

from gi.repository import GLib, Gdk, Gtk, Pango

from . import config, themes

SAVE_DELAY_MS = 350


def _rgb(hex_color):
    c = Gdk.RGBA()
    c.parse(hex_color)
    return c.red, c.green, c.blue


def _hex(rgba):
    return '#%02x%02x%02x' % (int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255))


class ThemeCard(Gtk.EventBox):
    """A tiny picture of the theme: a terminal with a prompt, output and an error."""

    def __init__(self, name, on_pick):
        super().__init__()
        self.name = name
        th = themes.THEMES[name]
        self.get_style_context().add_class('chiral-card')
        self.set_tooltip_text(th['label'])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add(box)
        area = Gtk.DrawingArea()
        area.set_size_request(168, 92)
        area.connect('draw', self._draw)
        box.pack_start(area, False, False, 0)
        label = Gtk.Label(label=th['label'], xalign=0)
        label.set_margin_start(2)
        box.pack_start(label, False, False, 0)
        self.connect('button-press-event', lambda *_: on_pick(name))

    def _draw(self, area, cr):
        th = themes.THEMES[self.name]
        w, h = area.get_allocated_width(), area.get_allocated_height()
        r = 7
        cr.new_path()
        cr.arc(w - r, r, r, -math.pi / 2, 0)
        cr.arc(w - r, h - r, r, 0, math.pi / 2)
        cr.arc(r, h - r, r, math.pi / 2, math.pi)
        cr.arc(r, r, r, math.pi, 1.5 * math.pi)
        cr.close_path()
        cr.set_source_rgb(*_rgb(th['bg']))
        cr.fill_preserve()
        cr.set_source_rgb(*_rgb(th['line']))
        cr.set_line_width(1)
        cr.stroke()
        cr.set_source_rgb(*_rgb(th['hdr']))                 # a title bar with the accent dot
        cr.rectangle(1, 1, w - 2, 12)
        cr.fill()
        cr.set_source_rgb(*_rgb(th['accent']))
        cr.arc(9, 7, 3, 0, 2 * math.pi)
        cr.fill()
        pal = th['palette']
        rows = [[(pal[2], 18), (th['fg'], 4), (pal[4], 30), (th['fg'], 22)],
                [(th['fg'], 60), (th['dim'], 30)],
                [(pal[4], 20), (pal[2], 26), (th['fg'], 34)],
                [(pal[1], 70)],
                [(pal[3], 24), (th['fg'], 40), (pal[5], 18)],
                [(pal[2], 18), (th['fg'], 4), (th['accent'], 8)]]
        y = 20
        for row in rows:
            x = 8
            for color, length in row:
                cr.set_source_rgb(*_rgb(color))
                cr.rectangle(x, y, length, 5)
                cr.fill()
                x += length + 5
            y += 11
        return False

    def set_selected(self, on):
        ctx = self.get_style_context()
        (ctx.add_class if on else ctx.remove_class)('selected')


class Swatch(Gtk.EventBox):
    def __init__(self, name, color_fn, on_pick):
        super().__init__()
        self.name = name
        self.color_fn = color_fn
        self.selected = False
        self.set_tooltip_text('the theme\'s own accent' if name == 'theme' else name)
        area = Gtk.DrawingArea()
        area.set_size_request(34, 34)
        area.connect('draw', self._draw)
        self.area = area
        self.add(area)
        self.connect('button-press-event', lambda *_: on_pick(name))

    def _draw(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        cx, cy, rad = w / 2, h / 2, min(w, h) / 2 - 5
        cr.set_source_rgb(*_rgb(self.color_fn()))
        cr.arc(cx, cy, rad, 0, 2 * math.pi)
        cr.fill()
        if self.name == 'theme':                           # a small "T" marks "follow the theme"
            cr.set_source_rgba(0, 0, 0, 0.45)
            cr.select_font_face('Sans', 0, 1)
            cr.set_font_size(12)
            cr.move_to(cx - 4, cy + 4)
            cr.show_text('T')
        if self.selected:
            cr.set_source_rgb(*_rgb('#ffffff'))
            cr.set_line_width(2)
            cr.arc(cx, cy, rad + 3, 0, 2 * math.pi)
            cr.stroke()
        return False


class SettingsWindow(Gtk.Window):
    def __init__(self, win):
        super().__init__(title='Chiral Settings')
        self.win = win
        self.set_transient_for(win)
        self.set_default_size(880, 620)
        self.get_style_context().add_class('chiral-settings')
        self._save_source = 0
        self._building = True

        header = Gtk.HeaderBar(title='Chiral Settings', subtitle='changes apply immediately')
        header.set_show_close_button(True)
        file_btn = Gtk.Button(label='Open settings file')
        file_btn.connect('clicked', lambda *_: (self.win.open_file(config.CONFIG_PATH), self.win.present()))
        reset_btn = Gtk.Button(label='Reset to defaults')
        reset_btn.connect('clicked', self._reset)
        header.pack_end(file_btn)
        header.pack_start(reset_btn)
        self.set_titlebar(header)

        body = Gtk.Box()
        self.add(body)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self.stack)
        sidebar.set_size_request(170, -1)
        body.pack_start(sidebar, False, False, 0)
        body.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        body.pack_start(self.stack, True, True, 0)

        self._page_appearance()
        self._page_font()
        self._page_behavior()
        self._page_agents()
        self._page_team()
        self._page_keys()
        self._building = False
        self.connect('key-press-event', self._on_key)
        self.show_all()

    # ---------- plumbing ----------
    def cfg(self):
        return self.win.cfg

    def get(self, path, default=None):
        node = self.cfg()
        for part in path.split('.'):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, path, value):
        if self._building:
            return
        parts = path.split('.')
        node = self.cfg()
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        if node.get(parts[-1]) == value:
            return
        node[parts[-1]] = value
        self.win.apply_config()
        if path in ('tree.show_hidden',) and self.win.panel_open('tree'):
            self.win.tree.refresh(self.win.tree.root or self.win.cwd)
        self._schedule_save()

    def _schedule_save(self):
        if self._save_source:
            GLib.source_remove(self._save_source)
        self._save_source = GLib.timeout_add(SAVE_DELAY_MS, self._save)

    def _save(self):
        self._save_source = 0
        try:
            self.win.last_saved_settings = config.save(self.cfg())
        except OSError as e:
            self.win.toast('could not save settings: %s' % e)
        return False

    def _on_key(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _page(self, name, title):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for side in ('start', 'end', 'top', 'bottom'):
            getattr(box, 'set_margin_' + side)(24 if side in ('start', 'end') else 18)
        scroll.add(box)
        self.stack.add_titled(scroll, name, title)
        return box

    @staticmethod
    def _heading(box, text):
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup('<b>%s</b>' % GLib.markup_escape_text(text))
        lbl.set_margin_top(12)
        box.pack_start(lbl, False, False, 0)

    @staticmethod
    def _row(box, label, widget, hint=None):
        row = Gtk.Box(spacing=12)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        lbl = Gtk.Label(label=label, xalign=0)
        left.pack_start(lbl, False, False, 0)
        if hint:
            h = Gtk.Label(label=hint, xalign=0)
            h.set_line_wrap(True)
            h.set_max_width_chars(60)
            h.get_style_context().add_class('dim-label')
            h.set_attributes(_small())
            left.pack_start(h, False, False, 0)
        row.pack_start(left, True, True, 0)
        widget.set_valign(Gtk.Align.CENTER)
        row.pack_end(widget, False, False, 0)
        row.set_margin_top(4)
        row.set_margin_bottom(4)
        box.pack_start(row, False, False, 0)

    def _switch(self, path, default=False):
        sw = Gtk.Switch()
        sw.set_active(bool(self.get(path, default)))
        sw.connect('notify::active', lambda s, _p: self.set(path, s.get_active()))
        return sw

    def _combo(self, path, options, default):
        combo = Gtk.ComboBoxText()
        for value, text in options:
            combo.append(value, text)
        combo.set_active_id(str(self.get(path, default)))
        combo.connect('changed', lambda c: self.set(path, c.get_active_id()))
        return combo

    def _spin(self, path, lo, hi, step, default, digits=0):
        spin = Gtk.SpinButton.new_with_range(lo, hi, step)
        spin.set_digits(digits)
        spin.set_value(float(self.get(path, default)))

        def changed(s):
            v = s.get_value()
            self.set(path, round(v, digits) if digits else int(v))
        spin.connect('value-changed', changed)
        return spin

    def _entry(self, path, default='', to_value=None, from_value=None, width=28):
        e = Gtk.Entry()
        e.set_width_chars(width)
        v = self.get(path, default)
        e.set_text(from_value(v) if from_value else str(v))
        source = [0]

        def changed(entry):
            if source[0]:
                GLib.source_remove(source[0])

            def commit():
                source[0] = 0
                text = entry.get_text()
                self.set(path, to_value(text) if to_value else text)
                return False
            source[0] = GLib.timeout_add(500, commit)
        e.connect('changed', changed)
        return e

    # ---------- pages ----------
    def _page_appearance(self):
        box = self._page('appearance', 'Appearance')
        self.cards = []
        for title, dark in (('Dark themes', True), ('Light themes', False)):
            self._heading(box, title)
            flow = Gtk.FlowBox()
            flow.set_selection_mode(Gtk.SelectionMode.NONE)
            flow.set_max_children_per_line(4)
            flow.set_min_children_per_line(2)
            flow.set_column_spacing(10)
            flow.set_row_spacing(10)
            for name, th in themes.THEMES.items():
                if th['dark'] == dark:
                    card = ThemeCard(name, self._pick_theme)
                    card.set_selected(name == self.get('theme'))
                    self.cards.append(card)
                    flow.add(card)
            box.pack_start(flow, False, False, 0)

        self._heading(box, 'Accent colour')
        hint = Gtk.Label(label='Borders of the focused terminal, the cursor, highlights. "T" follows the theme.', xalign=0)
        hint.get_style_context().add_class('dim-label')
        box.pack_start(hint, False, False, 0)
        row = Gtk.Box(spacing=4)
        self.swatches = []
        for name, color in themes.ACCENTS.items():
            fn = (lambda: themes.get(dict(self.cfg(), accent='theme'))[1]) if color is None else (lambda c=color: c)
            sw = Swatch(name, fn, self._pick_accent)
            self.swatches.append(sw)
            row.pack_start(sw, False, False, 0)
        self.custom = Gtk.ColorButton()
        self.custom.set_tooltip_text('pick any colour')
        self.custom.connect('color-set', lambda b: self._pick_accent(_hex(b.get_rgba())))
        row.pack_start(self.custom, False, False, 8)
        box.pack_start(row, False, False, 0)
        self._mark_accent()

        self._heading(box, 'Motion')
        self._row(box, 'Moving strands behind the text', self._switch_value('background', 'strands', 'off'),
                  'Faint strands stretching from top to bottom, like a chiral network.')
        self._row(box, 'Animations', self._combo('animations', [('normal', 'Normal'), ('fast', 'Fast'), ('off', 'Off')], 'normal'),
                  'Panels sliding in, the strands and the logo glitch. Off keeps everything still.')

    def _switch_value(self, path, on_value, off_value):
        sw = Gtk.Switch()
        sw.set_active(self.get(path, on_value) == on_value)
        sw.connect('notify::active', lambda s, _p: self.set(path, on_value if s.get_active() else off_value))
        return sw

    def _pick_theme(self, name):
        self.set('theme', name)
        for card in self.cards:
            card.set_selected(card.name == name)
        self._mark_accent()
        self._sync_dark()
        return True

    def _pick_accent(self, name):
        self.set('accent', name)
        self._mark_accent()
        return True

    def _mark_accent(self):
        current = self.get('accent', 'theme')
        for sw in self.swatches:
            sw.selected = sw.name == current
            sw.area.queue_draw()
        c = Gdk.RGBA()
        c.parse(themes.get(self.cfg())[1])
        self.custom.set_rgba(c)

    def _sync_dark(self):
        th, _ = themes.get(self.cfg())
        Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', th['dark'])

    def _page_font(self):
        box = self._page('font', 'Font')
        self._heading(box, 'Font')
        fb = Gtk.FontButton()
        fb.set_show_size(False)
        fb.set_filter_func(lambda family, _face, *_: family.is_monospace())
        fb.set_font('%s 12' % self.get('font.family', 'Monospace'))
        fb.connect('font-set', lambda b: self.set('font.family', Pango.FontDescription.from_string(b.get_font()).get_family()))
        self._row(box, 'Family', fb, 'Only monospace fonts are listed.')
        self._row(box, 'Size of the main terminal', self._spin('font.size', 6, 40, 1, 12), 'In points.')
        self._row(box, 'Line height', self._spin('font.line_height', 1.0, 2.0, 0.05, 1.0, digits=2))
        self._heading(box, 'Automatic sizing')
        self._row(box, 'Sub-terminals size their font to fit', self._switch('font.auto', True),
                  'Small windows get a small font, big ones a big font.')
        self._row(box, 'Aim for this many columns', self._spin('font.auto_columns', 40, 200, 5, 80))
        self._row(box, 'Smallest font', self._spin('font.auto_min', 5, 20, 1, 7))
        self._row(box, 'Largest font', self._spin('font.auto_max', 8, 40, 1, 16))
        self._row(box, 'Main terminal shrinks when squeezed', self._switch('font.main_auto', True),
                  'When the file tree takes space beside it.')
        self._row(box, 'Unfocused columns are smaller by', self._spin('font.unfocused_drop', 0, 10, 1, 3),
                  'Points. With Shift+→ columns, the focused one keeps the full size.')

    def _page_behavior(self):
        box = self._page('behavior', 'Behavior')
        self._heading(box, 'Top bar')
        self._row(box, 'Terminal awareness bar', self._switch('awareness', True),
                  'git branch and changes, H for binary files, py / node / docker / make.')
        self._heading(box, 'File tree (Ctrl+O)')
        self._row(box, 'Open when the mouse touches the left edge', self._switch('tree.hover', True))
        self._row(box, 'Live preview while moving through it', self._switch('tree.preview', True),
                  'Folders as a shell there, binaries in hex, text read-only.')
        self._row(box, 'Show hidden files', self._switch('tree.show_hidden', False))
        self._heading(box, 'Programs')
        self._row(box, 'Open in a floating window', self._entry(
            'popout', [], to_value=lambda t: [p for p in t.replace(',', ' ').split() if p],
            from_value=lambda v: ' '.join(v)),
            'When typed in the main terminal. Separate names with spaces. (Applies to new terminals.)')
        self._row(box, 'Editor', self._entry('editor', ''), 'Empty: your $EDITOR, else nano.')

    def _page_agents(self):
        box = self._page('agents', 'AI agents')
        self._heading(box, 'AI agents (Shift+↑ → AI agent)')
        self._row(box, 'Default agent', self._combo('claude.default_agent', [('claude', 'Claude Code'), ('codex', 'Codex'), ('local', 'Local AI (Ollama)')], 'claude'))
        self._row(box, 'Watching', self._combo('claude.watch', [('auto', 'Explain failed commands automatically'),
                                                                ('notify', 'Only show failures'), ('off', 'Off')], 'auto'),
                  'Every command you finish is logged for the agents to read.')
        self._row(box, 'Claude command', self._entry('claude.command', 'claude'))
        self._row(box, 'Codex command', self._entry('claude.codex_command', 'codex'))

    def _page_team(self):
        from . import session
        box = self._page('team', 'Team')
        self._heading(box, 'Team sessions')
        info = Gtk.Label(xalign=0)
        info.set_line_wrap(True)
        info.set_max_width_chars(70)
        info.set_markup('Turn <b>N</b> on in the top bar to let the people below see your terminals (and type, if '
                        'you allow it). <b>NC</b> lists them, shows who is sharing, and opens their terminals.\n'
                        '<span alpha="65%">The connection is not encrypted: use it on a trusted network, or over '
                        'Tailscale.</span>')
        box.pack_start(info, False, False, 0)
        mine = session.my_addresses()
        self._row(box, 'Your address', Gtk.Label(label=', '.join(mine) or 'unknown', selectable=True),
                  'Give this to your teammates so they can add you.')
        self._row(box, 'Your name', self._entry('sharing.name', '', width=24), 'Empty: %s' % session.my_name())
        self._row(box, 'Port', self._spin('sharing.port', 1024, 65535, 1, session.DEFAULT_PORT),
                  'The same for everyone in the team.')
        self._row(box, 'People watching you may type', self._switch('sharing.allow_input', True))

        self._heading(box, 'People who may join you')
        self.peer_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(self.peer_list, False, False, 0)
        for name, ip in session.parse_peers(self.get('sharing.peers', [])):
            self._peer_row(name, ip)
        add = Gtk.Button(label='+ Add person')
        add.set_halign(Gtk.Align.START)
        add.connect('clicked', lambda *_: self._peer_row('', '', focus=True))
        box.pack_start(add, False, False, 4)

    def _peer_row(self, name, ip, focus=False):
        row = Gtk.Box(spacing=8)
        name_e = Gtk.Entry(placeholder_text='name', text=name)
        name_e.set_width_chars(18)
        ip_e = Gtk.Entry(placeholder_text='IP address, e.g. 192.168.1.20', text=ip)
        ip_e.set_width_chars(22)
        rm = Gtk.Button(label='Remove')
        row.pack_start(name_e, False, False, 0)
        row.pack_start(ip_e, False, False, 0)
        row.pack_start(rm, False, False, 0)
        self.peer_list.pack_start(row, False, False, 0)
        row.show_all()
        for e in (name_e, ip_e):
            e.connect('changed', lambda *_: self._save_peers())
        row.fw_ip = ip.strip() or None      # the address we last asked about for the firewall
        ip_e.connect('activate', lambda *_: self._firewall_add(row, ip_e.get_text().strip()))
        ip_e.connect('focus-out-event', lambda *_: (self._firewall_add(row, ip_e.get_text().strip()), False)[1])
        rm.connect('clicked', lambda *_: self._remove_peer(row, ip_e.get_text().strip()))
        if focus:
            name_e.grab_focus()

    # --- firewall (ufw): teammates can only reach N when their address is allowed through it ---
    def _firewall_add(self, row, ip):
        from . import session
        if not ip or ip == row.fw_ip or not session.valid_ip(ip):
            return
        row.fw_ip = ip
        if not session.firewall_enabled():
            return                                  # no firewall running: nothing to open
        port = int(self.get('sharing.port', session.DEFAULT_PORT))
        cmd = 'sudo ufw allow from %s to any port %d proto tcp comment "chiral team session"' % (ip, port)
        if self._confirm('Allow %s through the firewall?' % ip,
                         'Your firewall is on, so this person cannot reach your N session yet.\n'
                         'Chiral will run this in a floating terminal (it asks for your password):\n\n'
                         '<tt>%s</tt>' % GLib.markup_escape_text(cmd), 'Allow'):
            self.win._run_setup('firewall: allow %s' % ip, cmd)
            self.win.present()

    def _remove_peer(self, row, ip):
        from . import session
        self.peer_list.remove(row)
        self._save_peers()
        if not ip or not session.valid_ip(ip) or not session.firewall_enabled():
            return
        port = int(self.get('sharing.port', session.DEFAULT_PORT))
        cmd = 'sudo ufw delete allow from %s to any port %d proto tcp' % (ip, port)
        if self._confirm('Also close the firewall for %s?' % ip,
                         'Chiral will run:\n\n<tt>%s</tt>' % GLib.markup_escape_text(cmd), 'Close it'):
            self.win._run_setup('firewall: remove %s' % ip, cmd)
            self.win.present()

    def _confirm(self, title, markup, ok):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.NONE, text=title)
        dlg.format_secondary_markup(markup)
        dlg.add_button('Not now', Gtk.ResponseType.CANCEL)
        dlg.add_button(ok, Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        answer = dlg.run()
        dlg.destroy()
        return answer == Gtk.ResponseType.OK

    def _save_peers(self):
        from . import session
        peers = []
        for row in self.peer_list.get_children():
            name_e, ip_e = row.get_children()[:2]
            ip = ip_e.get_text().strip()
            ok = not ip or session.valid_ip(ip)
            ctx = ip_e.get_style_context()
            (ctx.remove_class if ok else ctx.add_class)('error')      # red until it is a real address
            ip_e.set_tooltip_text(None if ok else 'not an IP address (e.g. 192.168.1.20)')
            if ip and ok:
                name = name_e.get_text().strip().replace('=', ' ')
                peers.append('%s=%s' % (name, ip) if name else ip)
        self.set('sharing.peers', peers)

    def _page_keys(self):
        box = self._page('keys', 'Keys')
        self._heading(box, 'When a program such as nano runs')
        self._row(box, 'Shift + arrows', self._combo('keys.shift_arrows', [('smart', 'Go to the program (smart)'),
                                                                           ('always', 'Always Chiral')], 'smart'),
                  'Ctrl+Shift+arrows always reach Chiral.')
        self._row(box, 'Ctrl + ← / →', self._combo('keys.ctrl_arrows', [('smart', 'Move focus, programs keep them (smart)'),
                                                                       ('always', 'Always move focus'), ('off', 'Off')], 'smart'))
        self._heading(box, 'All shortcuts')
        keys = [
            ('Shift+→ / Shift+←', 'add / close a terminal column'),
            ('Ctrl+← / Ctrl+→', 'move focus between terminals'),
            ('Shift+↑', 'command bar (AI agent, themes, files, commands)'),
            ('Shift+↓', 'window bar: every floating window'),
            ('Ctrl+O', 'file tree with live preview'),
            ('Ctrl+Shift+T / W', 'new / close floating terminal'),
            ('Ctrl+Shift+E', 'AI agent explains the last failure'),
            ('Ctrl + wheel, Ctrl+= / Ctrl+-', 'zoom the terminal · Ctrl+0 resets'),
            ('Ctrl+Shift+C / V', 'copy / paste'),
            ('Shift+↑ → settings', 'these settings (or settings: appearance, font, …)'),
        ]
        grid = Gtk.Grid(column_spacing=24, row_spacing=6)
        for i, (k, what) in enumerate(keys):
            kl = Gtk.Label(xalign=0)
            kl.set_markup('<tt>%s</tt>' % GLib.markup_escape_text(k))
            grid.attach(kl, 0, i, 1, 1)
            grid.attach(Gtk.Label(label=what, xalign=0), 1, i, 1, 1)
        box.pack_start(grid, False, False, 6)

    # ---------- reset ----------
    def _reset(self, *_):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.OK_CANCEL, text='Reset all settings to their defaults?')
        answer = dlg.run()
        dlg.destroy()
        if answer != Gtk.ResponseType.OK:
            return
        self.win.cfg.clear()
        self.win.cfg.update(copy.deepcopy(config.DEFAULTS))
        self.win.app.cfg = self.win.cfg
        self.win.apply_config()
        self._save()
        self.win.settings_window = None
        self.destroy()
        self.win.open_settings()


def _small():
    attrs = Pango.AttrList()
    attrs.insert(Pango.attr_scale_new(0.85))
    return attrs
