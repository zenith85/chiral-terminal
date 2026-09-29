"""Terminal awareness: a thin bar on top that shows what is in the folder you are working in.

It follows the focused terminal's folder: a git repository shows git's logo with the branch and
changes, binary files show H, and project markers show py / node / docker / make / venv.
Detection runs in a background thread so a slow `git status` never blocks typing.
"""
import math
import os
import subprocess
import shutil
import threading

from gi.repository import GLib, Gtk

from .agent_chips import AgentChips
from .brand import BrandMark
from . import session

BINARY_EXT = {'.bin', '.hex', '.elf', '.o', '.so', '.a', '.img', '.iso', '.dat', '.exe', '.dll',
              '.class', '.pyc', '.dfu', '.uf2', '.srec', '.fw', '.rom', '.dump'}
MAX_ENTRIES = 400          # never scan huge folders completely
SNIFF_LIMIT = 40           # files without a known extension that we peek into
REFRESH_S = 5


def _is_binary(path):
    try:
        with open(path, 'rb') as f:
            return b'\0' in f.read(4096)
    except OSError:
        return False


def _git(cwd):
    try:
        out = subprocess.run(['git', '-C', cwd, 'status', '--porcelain', '-b'], capture_output=True,
                             text=True, timeout=1.5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    lines = out.stdout.splitlines()
    head = lines[0][3:] if lines and lines[0].startswith('## ') else ''
    branch = head.split('...')[0].replace('No commits yet on ', '') or '?'
    ahead = behind = 0
    if '[' in head:
        for part in head[head.index('[') + 1:head.rindex(']')].split(','):
            part = part.strip()
            if part.startswith('ahead '):
                ahead = int(part.split()[1])
            elif part.startswith('behind '):
                behind = int(part.split()[1])
    return {'branch': branch, 'changed': len(lines) - 1, 'ahead': ahead, 'behind': behind}


def detect(cwd):
    info = {'cwd': cwd, 'git': _git(cwd), 'binaries': [], 'markers': []}
    try:
        with os.scandir(cwd) as it:
            entries = [e for _, e in zip(range(MAX_ENTRIES), it)]
    except OSError:
        return info
    names = {e.name for e in entries}
    sniffed = 0
    for e in entries:
        try:
            if not e.is_file() or e.name.startswith('.'):
                continue
        except OSError:
            continue
        ext = os.path.splitext(e.name)[1].lower()
        if ext in BINARY_EXT:
            info['binaries'].append(e.name)
        elif not ext and sniffed < SNIFF_LIMIT:
            sniffed += 1
            if _is_binary(e.path):
                info['binaries'].append(e.name)
    markers = info['markers']
    if names & {'pyproject.toml', 'setup.py', 'requirements.txt', 'Pipfile'} or any(n.endswith('.py') for n in names):
        markers.append(('py', 'Python project'))
    if 'package.json' in names:
        markers.append(('node', 'Node project (package.json)'))
    if names & {'Dockerfile', 'docker-compose.yml', 'docker-compose.yaml', 'compose.yaml', 'compose.yml'}:
        markers.append(('docker', 'Docker files here'))
    if names & {'Makefile', 'makefile', 'GNUmakefile'}:
        markers.append(('make', 'Makefile here'))
    if names & {'.venv', 'venv'}:
        markers.append(('venv', 'Python virtual environment in this folder'))
    return info


class GitMark(Gtk.DrawingArea):
    """Git's own logo (the orange diamond with a branch), drawn small."""

    def __init__(self):
        super().__init__()
        self.set_size_request(14, 14)
        self.connect('draw', self._draw)

    def _draw(self, _w, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        s = min(w, h)
        cr.translate(w / 2, h / 2)
        cr.rotate(math.pi / 4)
        half, r = s * 0.34, s * 0.08
        cr.new_path()
        cr.arc(half - r, -half + r, r, -math.pi / 2, 0)
        cr.arc(half - r, half - r, r, 0, math.pi / 2)
        cr.arc(-half + r, half - r, r, math.pi / 2, math.pi)
        cr.arc(-half + r, -half + r, r, math.pi, 1.5 * math.pi)
        cr.close_path()
        cr.set_source_rgb(0.94, 0.32, 0.20)            # git orange #f05133
        cr.fill()
        cr.rotate(-math.pi / 4)                         # branch drawn upright
        cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(max(1.0, s * 0.09))
        cr.move_to(-s * 0.02, -s * 0.24)
        cr.line_to(-s * 0.02, s * 0.24)
        cr.stroke()
        cr.move_to(-s * 0.02, -s * 0.12)
        cr.line_to(s * 0.16, s * 0.06)
        cr.stroke()
        for x, y in ((-s * 0.02, -s * 0.24), (-s * 0.02, s * 0.24), (s * 0.16, s * 0.06)):
            cr.arc(x, y, s * 0.075, 0, 2 * math.pi)
            cr.fill()
        return False


class AwarenessBar(Gtk.EventBox):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cwd = None
        self.info = None
        self._busy = False
        self._again = False
        self.get_style_context().add_class('forge-aware')
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)
        self.row = Gtk.Box(spacing=10)
        self.row.set_margin_start(8)
        self.row.set_margin_end(8)
        outer.pack_start(self.row, False, False, 0)
        outer.pack_start(Gtk.Separator(), False, False, 0)

        self.brand = BrandMark(win)
        self.row.pack_start(self.brand, False, False, 0)

        self.path = Gtk.Label(xalign=0)
        self.path.set_ellipsize(1)
        self.path.set_max_width_chars(40)
        self.path.get_style_context().add_class('forge-dim')
        self.row.pack_start(self.path, False, False, 0)

        self.git_btn = self._button(self._open_git)
        git_box = Gtk.Box(spacing=4)
        git_box.pack_start(GitMark(), False, False, 0)
        self.git_label = Gtk.Label()
        git_box.pack_start(self.git_label, False, False, 0)
        self.git_btn.add(git_box)
        self.row.pack_start(self.git_btn, False, False, 0)

        self.hex_btn = self._button(lambda *_: self.win.show_panel('tree'))
        self.hex_label = Gtk.Label()
        self.hex_btn.add(self.hex_label)
        self.row.pack_start(self.hex_btn, False, False, 0)

        self.markers = Gtk.Box(spacing=8)
        self.row.pack_start(self.markers, False, False, 0)

        self.right = Gtk.Label(xalign=1)
        self.right.get_style_context().add_class('forge-dim')
        self.row.pack_end(self.right, False, False, 0)
        self.agent_chips = AgentChips(win)          # Claude · Codex · Local, with usage orbs
        self.row.pack_end(self.agent_chips, False, False, 6)

        # team session: N = share my terminals, NC = see who is sharing and open theirs
        self.nc_btn = self._chip('NC', 'people on your list who are sharing · click to see their terminals', self._open_nc)
        self.n_btn = self._chip('N', 'share your terminals with the people in Settings → Team', lambda *_: self.win.toggle_share())
        self.row.pack_end(self.nc_btn, False, False, 0)
        self.row.pack_end(self.n_btn, False, False, 0)
        self.nc_popover = None
        self.update_share()
        GLib.timeout_add_seconds(REFRESH_S, self._tick)

    @staticmethod
    def _reveal(button):
        button.show()                      # show_all() skips widgets marked no_show_all
        button.get_child().show_all()

    def _chip(self, text, tip, cb):
        box = Gtk.EventBox()
        label = Gtk.Label()
        label.set_markup('<b>%s</b>' % text)
        box.add(label)
        box.label = label
        box.get_style_context().add_class('forge-share')
        box.set_tooltip_text(tip)
        box.connect('button-press-event', lambda *_: (cb(), True)[1])
        return box

    def update_share(self):
        share = getattr(self.win, 'share', None)
        ctx = self.n_btn.get_style_context()
        if share and share.on:
            ctx.add_class('on')
            n = share.watching_count()
            self.n_btn.label.set_markup('<b>N%s</b>' % (' · %d' % n if n else ''))
            names = ', '.join(sorted({v.name for v in share.viewers if v.term_id})) or 'nobody yet'
            self.n_btn.set_tooltip_text('sharing is ON · watching you: %s · click to stop' % names)
        else:
            ctx.remove_class('on')
            self.n_btn.label.set_markup('<b>N</b>')
            self.n_btn.set_tooltip_text('sharing is off · click to let the people in Settings → Team see your terminals')

    def _open_nc(self):
        """A list of everyone on my list: sharing or not, and their terminals to open."""
        cfg = self.win.cfg.get('sharing', {})
        peers = session.parse_peers(cfg.get('peers', []))
        port = int(cfg.get('port', session.DEFAULT_PORT))
        pop = Gtk.Popover.new(self.nc_btn)
        pop.set_position(Gtk.PositionType.BOTTOM)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for side in ('start', 'end', 'top', 'bottom'):
            getattr(box, 'set_margin_' + side)(10)
        pop.add(box)
        title = Gtk.Label(xalign=0)
        title.set_markup('<b>Team sessions</b>')
        box.pack_start(title, False, False, 0)
        waiting = Gtk.Label(label='checking %d %s…' % (len(peers), 'person' if len(peers) == 1 else 'people'), xalign=0)
        waiting.get_style_context().add_class('dim-label')
        offline = Gtk.Label(xalign=0)
        offline.set_line_wrap(True)
        offline.set_max_width_chars(50)
        offline.get_style_context().add_class('dim-label')
        state = {'left': len(peers), 'off': [], 'on': 0}
        if not peers:
            box.pack_start(Gtk.Label(label='Nobody on your list yet.', xalign=0), False, False, 0)
            btn = Gtk.Button(label='Settings → Team')
            btn.connect('clicked', lambda *_: (pop.popdown(), self.win.open_settings('team')))
            box.pack_start(btn, False, False, 0)
        for name, ip in peers:
            head = Gtk.Label(xalign=0)
            head.set_markup('<b>%s</b>  <span alpha="60%%">%s · checking…</span>' % (
                GLib.markup_escape_text(name), GLib.markup_escape_text(ip)))
            box.pack_start(head, False, False, 0)
            terms = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            terms.set_margin_start(12)
            box.pack_start(terms, False, False, 0)

            head.set_no_show_all(True)                  # only people with N on are listed
            terms.set_no_show_all(True)

            def finish_one():
                state['left'] -= 1
                if state['left'] <= 0:
                    waiting.set_text('' if state['on'] else 'nobody on your list has N on right now')
                    waiting.set_visible(not state['on'])
                if state['off']:
                    offline.set_text('not sharing now: ' + ', '.join(state['off']))
                    offline.show()

            def done(info, name=name, ip=ip, head=head, terms=terms):
                if 'error' in info:
                    state['off'].append(name)
                    finish_one()
                    return
                state['on'] += 1
                head.show()
                terms.show()
                who = info.get('name') or name
                head.set_markup('<b>%s</b>  <span alpha="60%%">%s · ● sharing as %s%s</span>' % (
                    GLib.markup_escape_text(name), ip, GLib.markup_escape_text(who),
                    '' if info.get('input', True) else ' (view only)'))
                for term in info.get('terms', []):
                    b = Gtk.Button(label='%s  (%d×%d)' % (term['title'], term.get('cols', 0), term.get('rows', 0)))
                    b.set_relief(Gtk.ReliefStyle.NONE)
                    b.get_child().set_xalign(0)
                    b.connect('clicked', lambda _b, t=term: (pop.popdown(),
                              self.win.open_remote(name, ip, port, t['id'], t['title'])))
                    terms.pack_start(b, False, False, 0)
                terms.show_all()
                finish_one()
            session.probe(self.win, name, ip, port, done)
        if peers:
            box.pack_start(waiting, False, False, 0)
            box.pack_start(offline, False, False, 0)
            offline.set_no_show_all(True)
        mine = session.my_addresses()
        foot = Gtk.Label(xalign=0)
        foot.set_markup('<span alpha="60%%">your address%s: %s · port %d</span>' % (
            'es' if len(mine) > 1 else '', ', '.join(mine) or '?', port))
        box.pack_start(foot, False, False, 0)
        box.show_all()
        pop.popup()
        self.nc_popover = pop

    def _button(self, cb):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.set_can_focus(False)
        b.get_style_context().add_class('forge-aware-item')
        b.connect('clicked', cb)
        b.set_no_show_all(True)
        return b

    # --- updates ---
    def follow(self, cwd):
        """Show the folder of the focused terminal."""
        if cwd and cwd != self.cwd:
            self.cwd = cwd
            self.refresh()

    def refresh(self):
        if not self.cwd:
            return
        if self._busy:
            self._again = True
            return
        self._busy = True
        cwd = self.cwd

        def work():
            info = detect(cwd)
            GLib.idle_add(self._apply, info)
        threading.Thread(target=work, daemon=True).start()

    def _tick(self):
        if self.get_mapped():
            self.refresh()
        self.update_right()
        return True

    def _apply(self, info):
        self._busy = False
        if self._again:
            self._again = False
            self.refresh()
        if info['cwd'] != self.cwd:
            return False
        self.info = info
        home = os.path.expanduser('~')
        self.path.set_text(info['cwd'].replace(home, '~', 1))

        g = info['git']
        if g:
            text = g['branch']
            if g['changed']:
                text += ' +%d' % g['changed']
            if g['ahead']:
                text += ' ↑%d' % g['ahead']
            if g['behind']:
                text += ' ↓%d' % g['behind']
            self.git_label.set_text(text)
            self.git_btn.set_tooltip_text('git: %s · %d changed file(s) · click to open gitk'
                                          % (g['branch'], g['changed']))
            self._reveal(self.git_btn)
        else:
            self.git_btn.hide()

        bins = info['binaries']
        if bins:
            self.hex_label.set_markup('<b>H</b> %d' % len(bins))
            shown = ', '.join(bins[:6]) + (' …' if len(bins) > 6 else '')
            self.hex_btn.set_tooltip_text('binary files: %s · click to open the tree, then x for hex' % shown)
            self._reveal(self.hex_btn)
        else:
            self.hex_btn.hide()

        for child in self.markers.get_children():
            self.markers.remove(child)
        for tag, tip in info['markers']:
            lbl = Gtk.Label(label=tag)
            lbl.set_tooltip_text(tip)
            lbl.get_style_context().add_class('forge-aware-tag')
            self.markers.pack_start(lbl, False, False, 0)
        self.markers.show_all()
        self.update_right()
        return False

    def update_right(self):
        subs = self.win.subs
        hidden = len([s for s in subs if not s.get_visible()])
        parts = []
        if self.win.columns:
            parts.append('%d col%s' % (len(self.win.columns), 's' if len(self.win.columns) > 1 else ''))
        if subs:
            parts.append('%d win%s' % (len(subs), ' (%d hidden)' % hidden if hidden else ''))
        agents = self.win.agents.summary()
        if agents:
            parts.append(agents)
        self.right.set_text('   '.join(parts))

    def _open_git(self, *_):
        cwd = self.cwd or self.win.cwd
        if shutil.which('gitk'):
            try:
                subprocess.Popen(['gitk', '--all'], cwd=cwd, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.win.toast('gitk: ' + os.path.basename(cwd))
                return
            except OSError as e:
                self.win.toast('could not start gitk: %s' % e)
        else:
            self.win.toast('gitk is not installed (sudo apt install gitk) - showing git status instead')
        self.win.run_float('git status -sb; echo; git log --oneline --graph --decorate -15', cwd=cwd)
