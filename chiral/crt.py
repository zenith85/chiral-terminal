"""CRT theme: phosphor persistence and a picture-tube look for the terminals.

Every frame the terminal is drawn offscreen and blended into a "phosphor" picture that is kept between
frames. Pixels that light up get there over ~0.15 s, so letters fade in as you type; pixels that go dark
fade a little faster, so lines that move (Enter, scrolling) leave a short ghost. Scanlines, a faint glow
and a vignette are laid on top. When nothing changes, the phosphor settles on the real picture.
"""
import time

import cairo
from gi.repository import GLib

RISE = 0.20          # per 16 ms, share of the way a brightening pixel moves to its new value
FALL = 0.34          # ... and a darkening one (the ghost of a moved letter)
FRAME_MS = 16
SETTLE_S = 0.32      # keep animating this long after the last change
GLOW = 0.055         # strength of each of the four 1-px glow copies
SCANLINE_PERIOD = 3  # px
SCANLINE_ALPHA = 0.22
VIGNETTE_ALPHA = 0.42


def _surface(w, h, scale, fmt=cairo.FORMAT_RGB24):
    s = cairo.ImageSurface(fmt, max(1, int(w * scale)), max(1, int(h * scale)))
    s.set_device_scale(scale, scale)
    return s


def _overlay(w, h, scale):
    """Scanlines and vignette, drawn once per size."""
    s = _surface(w, h, scale, cairo.FORMAT_ARGB32)
    cr = cairo.Context(s)
    cr.set_source_rgba(0, 0, 0, SCANLINE_ALPHA)
    y = SCANLINE_PERIOD - 1
    while y < h:
        cr.rectangle(0, y, w, 1)
        y += SCANLINE_PERIOD
    cr.fill()
    r = (w * w + h * h) ** 0.5 / 2
    g = cairo.RadialGradient(w / 2, h / 2, r * 0.45, w / 2, h / 2, r * 1.05)
    g.add_color_stop_rgba(0, 0, 0, 0, 0)
    g.add_color_stop_rgba(1, 0, 0, 0, VIGNETTE_ALPHA)
    cr.set_source(g)
    cr.paint()
    return s


class Phosphor:
    """The CRT picture of one terminal. `animate()` says whether persistence runs (CRT theme, animations on)."""

    def __init__(self, term, animate):
        self.term = term
        self.animate = animate
        self.inner = False           # True while the real terminal draws into our offscreen frame
        self.size = None
        self.frame = self.screen = self.tmp = self.overlay = None
        self.until = 0.0
        self.last = 0.0
        self.tick = 0
        term.connect('contents-changed', lambda *_: self.kick())
        term.connect('cursor-moved', lambda *_: self.kick())
        adj = term.get_vadjustment()
        if adj is not None:
            adj.connect('value-changed', lambda *_: self.kick())

    def kick(self):
        """The text changed: animate for a moment."""
        if not self.animate():
            return
        self.until = time.monotonic() + SETTLE_S
        if not self.tick:
            self.tick = GLib.timeout_add(FRAME_MS, self._tick)

    def _tick(self):
        self.term.queue_draw()
        if time.monotonic() > self.until:
            self.tick = 0
            return False
        return True

    def draw(self, cr):
        t = self.term
        w, h, scale = t.get_allocated_width(), t.get_allocated_height(), t.get_scale_factor()
        if w < 2 or h < 2:
            return False
        fresh = self.size != (w, h, scale)
        if fresh:
            self.size = (w, h, scale)
            self.frame, self.screen, self.tmp = (_surface(w, h, scale) for _ in range(3))
            self.overlay = _overlay(w, h, scale)

        self.inner = True                      # the terminal paints its background and text here
        try:
            t.draw(cairo.Context(self.frame))
        finally:
            self.inner = False

        now = time.monotonic()
        if not fresh and now <= self.until + 0.05 and self.animate():
            self._blend(min(max(now - self.last, 0.001), 0.1))
        else:                                  # settled: the phosphor shows the real picture
            sc = cairo.Context(self.screen)
            sc.set_operator(cairo.OPERATOR_SOURCE)
            sc.set_source_surface(self.frame, 0, 0)
            sc.paint()
        self.last = now

        cr.save()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_surface(self.screen, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_ADD)    # glow: the picture again, 1 px around, faintly
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            cr.set_source_surface(self.screen, dx, dy)
            cr.paint_with_alpha(GLOW)
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.set_source_surface(self.overlay, 0, 0)
        cr.paint()
        cr.restore()
        return True

    def _blend(self, dt):
        """screen = per pixel: brightening → slow step (RISE), darkening → fast step (FALL).
        Both steps are made; with RISE < FALL the darker of the two is the right one in either case."""
        steps = dt / 0.016
        k_rise = 1 - (1 - RISE) ** steps
        k_fall = 1 - (1 - FALL) ** steps
        tc = cairo.Context(self.tmp)
        tc.set_operator(cairo.OPERATOR_SOURCE)
        tc.set_source_surface(self.screen, 0, 0)
        tc.paint()
        tc.set_operator(cairo.OPERATOR_OVER)
        tc.set_source_surface(self.frame, 0, 0)
        tc.paint_with_alpha(k_fall)
        sc = cairo.Context(self.screen)
        sc.set_source_surface(self.frame, 0, 0)
        sc.paint_with_alpha(k_rise)
        sc.set_operator(cairo.OPERATOR_DARKEN)
        sc.set_source_surface(self.tmp, 0, 0)
        sc.paint()
