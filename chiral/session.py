"""Team sessions: share your terminals with the people on your list, watch and type into theirs.

  N  (top bar)  your share switch. On: Chiral listens on the sharing port and accepts connections only
                from the IP addresses in Settings → Team. Off: nothing listens.
  NC (top bar)  everyone on your list, whether they are sharing, and their terminals. Click one to
                open it in a floating window: you see it live and what you type goes into it.

How it works: the host sends the visible screen of a watched terminal (text, colours, cursor) when it
changes, only the lines that changed; the viewer draws them in its own terminal and sends keystrokes
back. Messages are one JSON object per line over TCP. The traffic is NOT encrypted: use it on a trusted
network or over an encrypted one such as Tailscale.
"""
import base64
import math
import time
import getpass
import json
import os
import socket
import subprocess

from gi.repository import GLib, Gio, Gtk

from . import fonts

DEFAULT_PORT = 47800
BUZZ_GAP_S = 2.0          # one buzz per person every 2 seconds at most
FRAME_MS = 70
PROTOCOL = 1


def my_name():
    return '%s@%s' % (getpass.getuser(), socket.gethostname())


def my_addresses():
    try:
        out = subprocess.run(['hostname', '-I'], capture_output=True, text=True, timeout=2).stdout
        return [a for a in out.split() if ':' not in a]
    except (OSError, subprocess.SubprocessError):
        return []


def firewall_enabled():
    """True when ufw is installed and switched on (then teammates need a rule to reach us)."""
    try:
        with open('/etc/ufw/ufw.conf') as f:
            return any(line.strip().lower() == 'enabled=yes' for line in f)
    except OSError:
        return False


def valid_ip(text):
    import ipaddress
    try:
        ipaddress.ip_address(text.strip())
        return True
    except ValueError:
        return False


def parse_peers(entries):
    """["Ali=192.168.1.20", "10.0.0.7"] -> [("Ali", "192.168.1.20"), ("10.0.0.7", "10.0.0.7")]"""
    peers = []
    for e in entries or []:
        e = str(e).strip()
        if not e:
            continue
        name, _, ip = e.rpartition('=')
        ip = ip.strip()
        peers.append(((name.strip() or ip), ip))
    return peers


def _norm_ip(ip):
    return ip[7:] if ip.startswith('::ffff:') else ip


def _send(conn, obj):
    try:
        conn.get_output_stream().write_all((json.dumps(obj, separators=(',', ':')) + '\n').encode(), None)
        return True
    except GLib.Error:
        return False


def _read_lines(conn, on_line, on_close):
    stream = Gio.DataInputStream.new(conn.get_input_stream())

    def got(s, res):
        try:
            line, _n = s.read_line_finish_utf8(res)
        except GLib.Error as e:
            if os.environ.get('CHIRAL_DEBUG'):
                print('chiral: read error:', e.message, flush=True)
            line = None
        if line is None:
            on_close()
            return
        try:
            msg = json.loads(line)
        except ValueError:
            msg = None
        if isinstance(msg, dict):
            on_line(msg)
        if not conn.is_closed():
            s.read_line_async(GLib.PRIORITY_DEFAULT, None, got)
    stream.read_line_async(GLib.PRIORITY_DEFAULT, None, got)


# ---------- the screen, as lines of ANSI ----------
def _rgb8(c):
    return (c.red >> 8, c.green >> 8, c.blue >> 8)


def snapshot(term, theme):
    """(cols, rows, [ansi line per row], (cursor_row, cursor_col)) of what is visible now."""
    cols, rows = term.get_column_count(), term.get_row_count()
    top = int(term.get_vadjustment().get_value())
    try:
        res = term.get_text_range(top, 0, top + rows - 1, cols - 1, None, None)
        text, attrs = res[0] or '', res[1] or []
    except (TypeError, GLib.Error):
        text, attrs = '', []
    dfg = tuple(int(theme['fg'][i:i + 2], 16) for i in (1, 3, 5))
    dbg = tuple(int(theme['bg'][i:i + 2], 16) for i in (1, 3, 5))
    cells = [[] for _ in range(rows)]
    for i, ch in enumerate(text):
        if ch == '\n' or i >= len(attrs):
            continue
        a = attrs[i]
        r = a.row - top
        if 0 <= r < rows:
            fg, bg = _rgb8(a.fore), _rgb8(a.back)
            ul = int(a.underline) & 1 if isinstance(a.underline, int) else bool(a.underline)   # VTE packs flags here
            cells[r].append((ch, None if fg == dfg else fg, None if bg == dbg else bg, bool(ul)))
    lines = []
    for row in cells:
        out, state = [], None
        for ch, fg, bg, ul in row:
            st = (fg, bg, ul)
            if st != state:
                codes = ['0']
                if fg:
                    codes.append('38;2;%d;%d;%d' % fg)
                if bg:
                    codes.append('48;2;%d;%d;%d' % bg)
                if ul:
                    codes.append('4')
                out.append('\x1b[%sm' % ';'.join(codes))
                state = st
            out.append(ch)
        if state is not None:
            out.append('\x1b[0m')
        lines.append(''.join(out))
    col, row = term.get_cursor_position()
    return cols, rows, lines, (row - top, col)


# ---------- host side (N) ----------
class Viewer:
    def __init__(self, server, conn, ip):
        self.server, self.conn, self.ip = server, conn, ip
        self.name = ip
        self.term_id = None
        self.last = None             # lines we sent last time, to send only changes
        self.last_size = None
        self.last_cursor = None
        self.last_buzz = 0.0


class ShareServer:
    def __init__(self, win):
        self.win = win
        self.service = None
        self.viewers = []
        self._watch_ids = {}          # terminal -> handler id
        self._dirty = set()
        self._frame_source = 0

    @property
    def on(self):
        return self.service is not None

    def cfg(self):
        return self.win.cfg.get('sharing', {})

    def allowed(self, ip):
        return any(_norm_ip(ip) == peer_ip for _name, peer_ip in parse_peers(self.cfg().get('peers', [])))

    def start(self):
        if self.service:
            return True
        port = int(self.cfg().get('port', DEFAULT_PORT))
        service = Gio.SocketService()
        try:
            service.add_inet_port(port, None)
        except GLib.Error as e:
            self.win.toast('could not share on port %d: %s' % (port, e.message))
            return False
        service.connect('incoming', self._incoming)
        service.start()
        self.service = service
        return True

    def stop(self):
        for v in list(self.viewers):
            self._drop(v, notify=False)
        if self.service:
            self.service.stop()
            self.service.close()
            self.service = None

    def team_column(self):
        return next((c for c in self.win.columns if getattr(c, 'team', False)), None)

    # terminals a viewer can pick. Folder mode (the default): only the locked team terminal.
    def terminals(self):
        w = self.win
        if self.cfg().get('mode', 'folder') == 'folder':
            team = self.team_column()
            if team is None:
                return []
            return [('col%d' % team.sid, team.term, 'team · %s' % (os.path.basename(team.folder) or team.folder))]
        out = [('main', w.main_term, 'main terminal')]
        for c in w.columns:
            out.append(('col%d' % c.sid, c.term, 'column %d' % c.number()))
        return out

    def _term(self, term_id):
        for tid, t, _title in self.terminals():
            if tid == term_id:
                return t
        return None

    def info(self):
        terms = []
        for tid, t, title in self.terminals():
            col = getattr(t, 'chiral_column', None)
            if col is not None and getattr(col, 'team', False):
                folder = ''                      # the team terminal's title already names its folder
            else:
                folder = ' · ' + self.win.cwd_of(t).replace(os.path.expanduser('~'), '~', 1)
            terms.append({'id': tid, 'title': '%s%s' % (title, folder),
                          'cols': t.get_column_count(), 'rows': t.get_row_count()})
        return {'t': 'info', 'v': PROTOCOL, 'name': self.cfg().get('name') or my_name(), 'sharing': True,
                'input': bool(self.cfg().get('allow_input', True)), 'terms': terms}

    def _incoming(self, _service, conn, _source):
        ip = _norm_ip(conn.get_remote_address().get_address().to_string())
        if not self.allowed(ip):
            _send(conn, {'t': 'refused', 'why': 'your address %s is not on this person\'s list' % ip})
            conn.close(None)
            return True
        v = Viewer(self, conn, ip)
        self.viewers.append(v)
        _read_lines(conn, lambda m: self._message(v, m), lambda: self._drop(v))
        return True

    def _message(self, v, m):
        kind = m.get('t')
        if kind == 'hello':
            v.name = str(m.get('name') or v.ip)[:60]
            _send(v.conn, self.info())
        elif kind == 'watch':
            t = self._term(m.get('term'))
            if t is None:
                _send(v.conn, {'t': 'gone', 'term': m.get('term')})
                return
            v.term_id, v.last, v.last_size, v.last_cursor = m.get('term'), None, None, None
            self._watch(t)
            self._send_frame(v, t)
            self.win.toast('%s is watching your %s' % (v.name, m.get('term')))
            self.win.aware.update_share()
        elif kind == 'buzz':
            now = time.monotonic()
            if now - v.last_buzz >= BUZZ_GAP_S:
                v.last_buzz = now
                self.win.buzzed(v.name)
        elif kind == 'input' and v.term_id and self.cfg().get('allow_input', True):
            t = self._term(v.term_id)
            if t is not None:
                try:
                    data = base64.b64decode(m.get('data', ''))
                except (ValueError, TypeError):
                    return
                try:
                    t.feed_child(data)
                except TypeError:
                    t.feed_child_binary(data)

    def _drop(self, v, notify=True):
        if v in self.viewers:
            self.viewers.remove(v)
            try:
                v.conn.close(None)
            except GLib.Error:
                pass
            if notify and v.term_id:
                self.win.toast('%s stopped watching' % v.name)
            self.win.aware.update_share()

    def watching_count(self):
        return len([v for v in self.viewers if v.term_id])

    # frames: when a watched terminal changes, send the changed lines a moment later
    def _watch(self, t):
        if t in self._watch_ids:
            return
        self._watch_ids[t] = (t.connect('contents-changed', lambda *_: self._mark(t)),
                              t.connect('cursor-moved', lambda *_: self._mark(t)))

    def _mark(self, t):
        self._dirty.add(t)
        if not self._frame_source:
            self._frame_source = GLib.timeout_add(FRAME_MS, self._flush)

    def _flush(self):
        self._frame_source = 0
        dirty, self._dirty = self._dirty, set()
        for v in list(self.viewers):
            t = self._term(v.term_id) if v.term_id else None
            if t is not None and t in dirty:
                self._send_frame(v, t)
        return False

    def _send_frame(self, v, t):
        cols, rows, lines, cursor = snapshot(t, self.win.theme)
        full = v.last is None or v.last_size != (cols, rows)
        changed = {str(i): l for i, l in enumerate(lines) if full or i >= len(v.last) or v.last[i] != l}
        if not changed and cursor == v.last_cursor:
            return
        ok = _send(v.conn, {'t': 'screen', 'cols': cols, 'rows': rows, 'full': full,
                            'lines': changed, 'cursor': list(cursor)})
        v.last, v.last_size, v.last_cursor = lines, (cols, rows), cursor
        if not ok:
            self._drop(v)


# ---------- viewer side (NC) ----------
def probe(win, name, ip, port, done):
    """Ask one peer what it shares. done(result) with result = info dict, or {'error': text}."""
    client = Gio.SocketClient()
    client.set_timeout(2)

    def connected(c, res):
        try:
            conn = c.connect_to_host_finish(res)
        except GLib.Error as e:
            done({'error': 'not sharing' if 'refused' in e.message.lower() else 'unreachable'})
            return
        answered = [False]

        def line(m):
            if answered[0]:
                return
            answered[0] = True
            if m.get('t') == 'info':
                done(m)
            else:
                done({'error': m.get('why') or 'refused'})
            conn.close(None)

        def closed():
            if not answered[0]:
                answered[0] = True
                done({'error': 'refused'})
        _read_lines(conn, line, closed)
        _send(conn, {'t': 'hello', 'name': win.cfg.get('sharing', {}).get('name') or my_name(), 'v': PROTOCOL})
    client.connect_to_host_async('%s:%d' % (ip, port), port, None, connected)


class RemoteView:
    """A floating window showing someone else's terminal; what you type goes to them."""

    def __init__(self, win, peer_name, ip, port, term_id, title):
        self.win = win
        self.term_id = term_id
        self.conn = None
        self.cols = self.rows = 0
        self.can_type = True
        self.sub = win.new_sub('%s · %s' % (peer_name, title), remote=True)
        self.sub.remote = self
        self.peer_name = peer_name
        self.bell = BellButton(self.buzz)
        self.bell.set_tooltip_text('Buzz %s: their Chiral shakes and rings (Ctrl+Shift+B)' % peer_name)
        self.sub.add_title_widget(self.bell)
        t = self.sub.term
        t.set_scrollback_lines(0)
        t.feed(b'\x1b[2mconnecting to %s ...\x1b[0m\r\n' % peer_name.encode())
        t.connect('commit', self._typed)
        client = Gio.SocketClient()
        client.set_timeout(4)
        client.connect_to_host_async('%s:%d' % (ip, port), port, None, self._connected)

    def _connected(self, c, res):
        try:
            self.conn = c.connect_to_host_finish(res)
        except GLib.Error as e:
            self._message_line('could not connect: %s' % e.message)
            return
        # the client's timeout was for connecting; a quiet terminal must not drop the connection
        self.conn.get_socket().set_timeout(0)
        self.conn.get_socket().set_keepalive(True)
        _read_lines(self.conn, self._message, self._closed)
        _send(self.conn, {'t': 'hello', 'name': self.win.cfg.get('sharing', {}).get('name') or my_name(), 'v': PROTOCOL})
        _send(self.conn, {'t': 'watch', 'term': self.term_id})

    def _message_line(self, text):
        self.sub.term.feed(('\r\n\x1b[2m[%s]\x1b[0m\r\n' % text).encode())

    def _closed(self):
        self._message_line('the session ended')
        self.conn = None

    def _message(self, m):
        kind = m.get('t')
        if kind == 'info':
            self.can_type = bool(m.get('input', True))
        elif kind == 'refused':
            self._message_line('refused: %s' % m.get('why', ''))
        elif kind == 'gone':
            self._message_line('that terminal is closed')
        elif kind == 'screen':
            self._draw(m)

    def _fit(self, cols, rows):
        """Pick a font so the other person's whole screen fits this window."""
        t, sub = self.sub.term, self.sub
        f = self.win.cfg['font']
        family = f.get('family', 'Monospace')
        w, h = sub.w - 12, sub.h - 30
        best = 5
        for size in range(20, 4, -1):
            cw = fonts.char_width(t, family, size)
            if cw * cols <= w and fonts.char_height(t, family, size) * rows <= h:
                best = size
                break
        sub.font_pinned = best
        sub._fit()

    def _draw(self, m):
        cols, rows = int(m.get('cols', 80)), int(m.get('rows', 24))
        if (cols, rows) != (self.cols, self.rows):
            self.cols, self.rows = cols, rows
            self._fit(cols, rows)
        out = ['\x1b[?25l']
        if m.get('full'):
            out.append('\x1b[0m\x1b[2J')
        visible = self.sub.term.get_row_count()
        for key, line in m.get('lines', {}).items():
            r = int(key)
            if r < visible:
                out.append('\x1b[%d;1H\x1b[0m\x1b[2K%s' % (r + 1, line))
        cr, cc = m.get('cursor', [0, 0])
        out.append('\x1b[0m\x1b[%d;%dH\x1b[?25h' % (min(cr, visible - 1) + 1, cc + 1))
        self.sub.term.feed(''.join(out).encode())

    def buzz(self):
        if self.conn is None:
            self.win.toast('not connected')
            return
        _send(self.conn, {'t': 'buzz'})
        self.bell.ring()
        self.win.toast('buzzed %s' % self.peer_name)

    def _typed(self, _t, text, _size):
        if self.conn is None or not self.can_type:
            return
        data = text.encode() if isinstance(text, str) else bytes(text)
        _send(self.conn, {'t': 'input', 'data': base64.b64encode(data).decode()})

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close(None)
            except GLib.Error:
                pass
            self.conn = None


class BellButton(Gtk.Button):
    """A small bell for a remote window's title bar; it swings when you buzz."""

    def __init__(self, on_click):
        super().__init__()
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.set_can_focus(False)
        self.swing_until = 0.0
        area = Gtk.DrawingArea()
        area.set_size_request(12, 12)
        area.connect('draw', self._draw)
        self.area = area
        self.add(area)
        self.connect('clicked', lambda *_: on_click())

    def ring(self):
        self.swing_until = time.monotonic() + 0.6

        def tick():
            self.area.queue_draw()
            return time.monotonic() < self.swing_until
        GLib.timeout_add(30, tick)

    def _draw(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        color = self.get_style_context().get_color(self.get_state_flags())
        left = self.swing_until - time.monotonic()
        angle = math.sin(left * 40) * 0.5 * max(0.0, left / 0.6) if left > 0 else 0.0
        cr.translate(w / 2, 1.5)
        cr.rotate(angle)
        s = min(w, h)
        cr.set_source_rgba(color.red, color.green, color.blue, 1)
        cr.move_to(-s * 0.36, s * 0.66)                      # the bell
        cr.curve_to(-s * 0.3, s * 0.15, -s * 0.22, s * 0.08, 0, s * 0.08)
        cr.curve_to(s * 0.22, s * 0.08, s * 0.3, s * 0.15, s * 0.36, s * 0.66)
        cr.close_path()
        cr.fill()
        cr.rectangle(-s * 0.42, s * 0.62, s * 0.84, s * 0.08)
        cr.fill()
        cr.arc(0, s * 0.8, s * 0.1, 0, 2 * math.pi)         # the clapper
        cr.fill()
        return False
