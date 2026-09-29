"""Top-bar icons for the AI agents: Claude, Codex and Local AI (Ollama).

Each shows an icon, its name and a small orb of liquid filled to how much of its 5-hour limit is
left (green → amber → red; Local is unlimited). Hover for the 5-hour and weekly numbers. Click:
install it (asks first), sign in / set it up (asks first), or, when ready, open an agent window.
"""
import math
import threading
import time

from gi.repository import GLib, Gdk, Gtk

from . import agent_status

REFRESH_S = 30
FRAME_MS = 90


def _rgb(hex_color):
    c = Gdk.RGBA()
    c.parse(hex_color)
    return c.red, c.green, c.blue


def _draw_icon(kind, cr, s, color):
    cr.set_source_rgb(*color)
    c = s / 2
    if kind == 'claude':                    # a spark
        cr.set_line_width(1.6)
        cr.set_line_cap(1)
        for i in range(8):
            a = i * math.pi / 4
            r = s * (0.44 if i % 2 == 0 else 0.3)
            cr.move_to(c, c)
            cr.line_to(c + r * math.cos(a), c + r * math.sin(a))
        cr.stroke()
    elif kind == 'codex':                   # angle brackets around a slash
        cr.set_line_width(1.5)
        cr.set_line_cap(1)
        cr.move_to(s * 0.3, s * 0.25)
        cr.line_to(s * 0.08, c)
        cr.line_to(s * 0.3, s * 0.75)
        cr.move_to(s * 0.7, s * 0.25)
        cr.line_to(s * 0.92, c)
        cr.line_to(s * 0.7, s * 0.75)
        cr.move_to(s * 0.58, s * 0.18)
        cr.line_to(s * 0.42, s * 0.82)
        cr.stroke()
    else:                                   # a chip with pins: runs on this computer
        cr.set_line_width(1.3)
        cr.rectangle(s * 0.25, s * 0.25, s * 0.5, s * 0.5)
        cr.stroke()
        for i in range(3):
            p = s * (0.34 + 0.16 * i)
            for (x0, y0, x1, y1) in ((p, s * 0.08, p, s * 0.25), (p, s * 0.75, p, s * 0.92),
                                     (s * 0.08, p, s * 0.25, p), (s * 0.75, p, s * 0.92, p)):
                cr.move_to(x0, y0)
                cr.line_to(x1, y1)
        cr.stroke()


ICON_COLORS = {'claude': '#d97757', 'codex': '#8fd0c4', 'local': '#a7c080'}


class AgentChip(Gtk.EventBox):
    def __init__(self, bar, kind):
        super().__init__()
        self.bar = bar
        self.kind = kind
        self.state = None
        self.get_style_context().add_class('forge-aware-item')
        box = Gtk.Box(spacing=4)
        self.add(box)
        self.icon = Gtk.DrawingArea()
        self.icon.set_size_request(13, 13)
        self.icon.connect('draw', self._draw_icon)
        self.label = Gtk.Label(label=agent_status.SPECS[kind]['label'])
        self.orb = Gtk.DrawingArea()
        self.orb.set_size_request(13, 17)
        self.orb.connect('draw', self._draw_orb)
        for w in (self.icon, self.label, self.orb):
            w.set_valign(Gtk.Align.CENTER)
            box.pack_start(w, False, False, 0)
        self.connect('button-press-event', lambda *_: (bar.win.agent_chip_clicked(kind), True)[1])
        self.set_tooltip_text('checking…')

    def phase(self):
        if not self.state:
            return 'unknown'
        if not self.state['installed']:
            return 'missing'
        return 'ready' if self.state['ready'] else 'setup'

    def left(self):
        u = (self.state or {}).get('usage') or {}
        if u.get('unlimited'):
            return 100.0
        w = u.get('short') or u.get('long')
        return w['left'] if w else None

    def update(self, state):
        self.state = state
        label = agent_status.SPECS[self.kind]['label']
        phase = self.phase()
        if phase == 'missing':
            tip = '%s is not installed · click to install' % label
        elif phase == 'setup':
            if self.kind == 'local':
                tip = ('Local AI: the Ollama server is not running · click to start it'
                       if not state.get('server') else 'Local AI: no model downloaded yet · click to choose one')
            else:
                tip = '%s is not signed in · click to sign in' % label
        else:
            u = state.get('usage') or {}
            if u.get('unlimited'):
                tip = 'Local AI · %s · runs on this computer, no limit · click to open an agent' % state.get('model')
            else:
                parts = [agent_status.describe_window(u[k], n) for k, n in (('short', '5-hour'), ('long', 'week')) if k in u]
                tip = '%s · %s · click to open an agent' % (label, ' · '.join(parts) if parts else 'usage not recorded yet')
                if u.get('captured'):
                    tip += '\n(as of %s, the last time %s recorded it)' % (
                        time.strftime('%a %H:%M', time.localtime(u['captured'])), label)
        self.set_tooltip_text(tip)
        self.label.set_opacity(1.0 if phase == 'ready' else 0.55)
        self.icon.queue_draw()
        self.orb.queue_draw()

    def _draw_icon(self, area, cr):
        s = min(area.get_allocated_width(), area.get_allocated_height())
        color = _rgb(ICON_COLORS[self.kind])
        if self.phase() != 'ready':
            color = tuple(0.45 * x + 0.25 for x in color)
        _draw_icon(self.kind, cr, s, color)
        return False

    def _draw_orb(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        t = time.monotonic() - self.bar.t0
        th = self.bar.win.theme
        bob = math.sin(t * 2.1 + hash(self.kind) % 7) * 1.2 if self.bar.animated() else 0
        cx, cy, r = w / 2, h / 2 + bob, min(w, h - 4) / 2 - 0.5
        phase = self.phase()
        dim = _rgb(th['dim'])
        if phase in ('missing', 'unknown'):
            cr.set_source_rgb(*dim)
            cr.set_line_width(1)
            cr.set_dash([1.5, 1.5])
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.stroke()
            cr.set_dash([])
            if phase == 'missing':                               # "+": install
                cr.move_to(cx - 2.5, cy)
                cr.line_to(cx + 2.5, cy)
                cr.move_to(cx, cy - 2.5)
                cr.line_to(cx, cy + 2.5)
                cr.stroke()
            return False
        if phase == 'setup':                                     # "!": needs signing in / setting up
            cr.set_source_rgb(*_rgb(th['palette'][3]))
            cr.set_line_width(1.2)
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.stroke()
            cr.move_to(cx, cy - 3)
            cr.line_to(cx, cy + 0.8)
            cr.stroke()
            cr.arc(cx, cy + 2.6, 0.8, 0, 2 * math.pi)
            cr.fill()
            return False
        left = self.left()
        frac = 1.0 if left is None else max(0.0, min(1.0, left / 100.0))
        color = th['palette'][2] if frac > 0.5 else th['palette'][3] if frac > 0.2 else th['palette'][1]
        rgb = _rgb(color)
        # glass
        cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 0.18)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()
        # liquid with a moving wave on top
        cr.save()
        cr.arc(cx, cy, r - 0.6, 0, 2 * math.pi)
        cr.clip()
        level = cy + r - 2 * r * frac
        amp = 0.9 if self.bar.animated() else 0
        cr.move_to(cx - r - 1, cy + r + 1)
        steps = 10
        for i in range(steps + 1):
            x = cx - r - 1 + (2 * r + 2) * i / steps
            cr.line_to(x, level + amp * math.sin(t * 3.0 + i * 0.9))
        cr.line_to(cx + r + 1, cy + r + 1)
        cr.close_path()
        cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 0.9)
        cr.fill()
        cr.restore()
        # rim and a small shine
        cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 0.9)
        cr.set_line_width(1)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        cr.set_source_rgba(1, 1, 1, 0.35)
        cr.arc(cx - r * 0.35, cy - r * 0.4, r * 0.18, 0, 2 * math.pi)
        cr.fill()
        return False


class AgentChips(Gtk.Box):
    KINDS = ('claude', 'codex', 'local')

    def __init__(self, win):
        super().__init__(spacing=10)
        self.win = win
        self.t0 = time.monotonic()
        self.tools = None
        self.states = {}
        self._busy = False
        self.chips = {k: AgentChip(self, k) for k in self.KINDS}
        for k in self.KINDS:
            self.pack_start(self.chips[k], False, False, 0)
        GLib.timeout_add_seconds(REFRESH_S, lambda: (self.refresh(), True)[1])
        GLib.timeout_add(FRAME_MS, self._tick)
        GLib.idle_add(lambda: (self.refresh(), False)[1])

    def animated(self):
        return self.win.cfg.get('animations', 'normal') != 'off'

    def _tick(self):
        if self.animated() and self.win.is_active() and self.get_mapped():
            for chip in self.chips.values():
                if chip.phase() == 'ready':
                    chip.orb.queue_draw()
        return True

    def refresh(self, find_tools=False):
        """Re-read status in the background (find_tools: look the programs up again, after installing)."""
        if self._busy:
            return
        self._busy = True
        if find_tools:
            self.tools = None
        local_model = self.win.cfg['claude'].get('local_model', '')

        def work():
            tools = self.tools or agent_status.find_tools()
            states = agent_status.status(tools, local_model)
            GLib.idle_add(self._apply, tools, states)
        threading.Thread(target=work, daemon=True).start()

    def _apply(self, tools, states):
        self._busy = False
        self.tools = tools
        self.states = states
        for kind, chip in self.chips.items():
            chip.update(states.get(kind))
        return False
