"""A sub-terminal: a small terminal window floating inside the main terminal.

Drag the title line to move it, the bottom-right corner to resize it, double-click the
title to fill the workspace. Its font follows its width unless pinned with Ctrl +/-/0.
"""
import math

import cairo
from gi.repository import GLib, Gdk, Gtk

from . import fonts

DOUBLE_CLICK = getattr(Gdk.EventType, 'DOUBLE_BUTTON_PRESS', None) or getattr(Gdk.EventType, '_2BUTTON_PRESS')
MOTION_MASKS = (Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                | Gdk.EventMask.POINTER_MOTION_MASK)


class SubWindow(Gtk.EventBox):
    def __init__(self, win, sid, title, app_mode):
        super().__init__()
        self.win = win
        self.sid = sid
        self.title = title
        self.app_mode = app_mode
        self.x, self.y, self.w, self.h = 60, 40, 640, 340
        self.font_pinned = None
        self.font_size = None
        self.prev_geom = None
        self._op = None
        self._fit_source = 0
        self.on_exit = None

        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.START)
        self.radius = 0                   # > 0: rounded corners (AI agents)
        self.connect('size-allocate', lambda *_: self._apply_shape())
        self.connect('realize', lambda *_: self._apply_shape())
        self.get_style_context().add_class('chiral-sub')

        layers = Gtk.Overlay()
        self.layers = layers
        self.set_border(2)
        self.add(layers)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        layers.add(box)

        self.titlebar = Gtk.EventBox()
        self.titlebar.get_style_context().add_class('chiral-title')
        self.titlebar.add_events(MOTION_MASKS)
        row = Gtk.Box(spacing=6)
        self.titlebar.add(row)
        self.label = Gtk.Label(xalign=0)
        self.label.set_ellipsize(3)       # Pango.EllipsizeMode.END
        self.meta = Gtk.Label()
        self.meta.get_style_context().add_class('chiral-meta')
        row.pack_start(self.label, True, True, 0)
        row.pack_start(self.meta, False, False, 0)
        self.title_row = row
        for text, tip, cb in (('_', 'Hide to the window bar (Shift+↓)', self._on_hide),
                              ('×', 'Close (Ctrl+Shift+W)', self._on_close)):
            b = Gtk.Button(label=text)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_can_focus(False)
            b.set_tooltip_text(tip)
            b.connect('clicked', cb)
            row.pack_start(b, False, False, 0)
        box.pack_start(self.titlebar, False, False, 0)

        self.term = win.make_terminal()
        self.term.chiral_sub = self
        self.term.chiral_is_app = app_mode
        box.pack_start(self.term, True, True, 0)

        grip = Gtk.EventBox()
        grip.set_size_request(14, 14)
        grip.set_halign(Gtk.Align.END)
        grip.set_valign(Gtk.Align.END)
        grip.get_style_context().add_class('chiral-grip')
        grip.add_events(MOTION_MASKS)
        layers.add_overlay(grip)

        self.titlebar.connect('button-press-event', self._press, 'move')
        grip.connect('button-press-event', self._press, 'resize')
        for w in (self.titlebar, grip):
            w.connect('motion-notify-event', self._motion)
            w.connect('button-release-event', self._release)
        self.term.connect('focus-in-event', lambda *_: self.win.focus_sub(self, grab=False))
        self.term.connect('size-allocate', lambda *_: GLib.idle_add(self._update_meta))
        self.update_title()

    def add_title_widget(self, widget):
        """Put a small button in the title bar, before the hide and close buttons."""
        self.title_row.pack_start(widget, False, False, 0)
        self.title_row.reorder_child(widget, 2)
        widget.show_all()

    def set_border(self, px):
        """Border thickness. Margins on the content (not set_border_width, whose area GTK does not
        paint for an EventBox) let our background show through as the border."""
        for side in ('start', 'end', 'top', 'bottom'):
            getattr(self.layers, 'set_margin_' + side)(px)

    def set_rounded(self, radius):
        self.radius = radius
        self._apply_shape()

    def _apply_shape(self):
        """Cut the window to a rounded rectangle, so the corners show what is behind it."""
        gdk_win = self.get_window()
        if not self.radius or gdk_win is None:
            return
        w, h, r = self.get_allocated_width(), self.get_allocated_height(), self.radius
        rects, prev, start = [], None, 0
        for y in range(h + 1):
            if y == h:
                inset = None
            else:
                d = (r - y - 0.5) if y < r else (y - (h - r) + 0.5) if y >= h - r else 0
                inset = int(math.ceil(r - math.sqrt(max(0.0, r * r - d * d)))) if d > 0 else 0
            if inset != prev:
                if prev is not None:
                    rects.append(cairo.RectangleInt(prev, start, max(0, w - 2 * prev), y - start))
                prev, start = inset, y
        region = cairo.Region(rects)
        gdk_win.shape_combine_region(region, 0, 0)
        gdk_win.input_shape_combine_region(region, 0, 0)

    # --- fixed size: the overlay gives us exactly w x h ---
    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.CONSTANT_SIZE

    def do_get_preferred_width(self):
        return self.w, self.w

    def do_get_preferred_height(self):
        return self.h, self.h

    def do_get_preferred_width_for_height(self, _h):
        return self.w, self.w

    def do_get_preferred_height_for_width(self, _w):
        return self.h, self.h

    # --- geometry ---
    def place(self, x=None, y=None, w=None, h=None, refit=True):
        area_w, area_h = self.win.workspace_size()
        if w is not None:
            self.w = int(max(220, min(w, area_w)))
        if h is not None:
            self.h = int(max(90, min(h, area_h)))
        if x is not None:
            self.x = int(max(-self.w + 80, min(x, area_w - 80)))
        if y is not None:
            self.y = int(max(0, min(y, area_h - 24)))
        self.set_margin_start(max(0, self.x))
        self.set_margin_top(self.y)
        self.queue_resize()
        if refit:
            self.schedule_fit()

    def toggle_maximize(self):
        area_w, area_h = self.win.workspace_size()
        if self.prev_geom:
            self.place(*self.prev_geom)
            self.prev_geom = None
        else:
            self.prev_geom = (self.x, self.y, self.w, self.h)
            self.place(0, 0, area_w, area_h)

    def _press(self, _w, ev, kind):
        if ev.button != 1:
            return False
        self.win.focus_sub(self)
        if kind == 'move' and ev.type == DOUBLE_CLICK:
            self._op = None
            self.toggle_maximize()
            return True
        self._op = (kind, ev.x_root, ev.y_root, self.x, self.y, self.w, self.h)
        return True

    def _motion(self, _w, ev):
        if not self._op:
            return False
        kind, sx, sy, x, y, w, h = self._op
        dx, dy = ev.x_root - sx, ev.y_root - sy
        if kind == 'move':
            self.place(x + dx, y + dy, refit=False)
        else:
            self.place(w=w + dx, h=h + dy)
        return True

    def _release(self, *_):
        self._op = None
        return False

    # --- font follows size ---
    def schedule_fit(self):
        if self._fit_source:
            GLib.source_remove(self._fit_source)
        self._fit_source = GLib.timeout_add(60, self._fit)

    def _fit(self):
        self._fit_source = 0
        font_cfg = self.win.cfg['font']
        if self.font_pinned:
            size = self.font_pinned
        elif font_cfg.get('auto', True):
            size = fonts.fit(self.term, self.w - 10, font_cfg)
        else:
            size = font_cfg.get('size', 12)
        if size != self.font_size:
            self.font_size = size
            self.term.set_font(fonts.desc(font_cfg.get('family', 'Monospace'), size))
        self._update_meta()
        return False

    def zoom(self, step):
        base = self.font_pinned or self.font_size or 11
        self.font_pinned = None if step == 0 else max(6, min(40, base + step))
        self._fit()

    def _update_meta(self):
        pin = '' if not self.font_pinned else ' pinned'
        self.meta.set_text('%spt%s %d×%d' % (self.font_size or '?', pin,
                                             self.term.get_column_count(), self.term.get_row_count()))
        return False

    def update_title(self):
        self.label.set_text('%d  %s' % (self.win.sub_number(self), self.title))

    def set_focused(self, on):
        ctx = self.get_style_context()
        (ctx.add_class if on else ctx.remove_class)('focused')

    def _on_hide(self, *_):
        self.win.hide_sub(self)

    def _on_close(self, *_):
        self.win.close_sub(self)
