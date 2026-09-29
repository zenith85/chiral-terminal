"""The innospaceone mark and the word NuERA, small, with an occasional glitch.

The mark: a square outline with a dot in its top-left corner, broken at the bottom-right where a
bold serif "1" breaks out of the frame. Every few seconds a short burst plays: color-split copies,
shifted horizontal slices and a flicker of swapped letters. With animations = "off" it stays still.
"""
import random

from gi.repository import GLib, Gdk, Gtk, Pango, PangoCairo

WORD = 'NuERA'
GLITCH_CHARS = '_#/|01█▚'
FRAME_MS = 45
BURST_FRAMES = (6, 11)
PAUSE_MS = (2600, 6500)
SPLIT_A = (0.94, 0.32, 0.36)     # red-ish copy
SPLIT_B = (0.30, 0.85, 0.92)     # cyan copy


def _rgb(hex_color):
    c = Gdk.RGBA()
    c.parse(hex_color)
    return c.red, c.green, c.blue


class BrandMark(Gtk.DrawingArea):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.frame = None            # None: still; else a dict describing this glitch frame
        self._left = 0
        self.set_size_request(74, 18)
        self.set_tooltip_text('innospaceone · NuERA')
        self.connect('draw', self._draw)
        self._schedule_burst()

    # --- animation ---
    def _enabled(self):
        return self.win.cfg.get('animations', 'normal') != 'off' and self.get_mapped()

    def _schedule_burst(self):
        GLib.timeout_add(random.randint(*PAUSE_MS), self._start_burst)

    def _start_burst(self):
        if self._enabled():
            self._left = random.randint(*BURST_FRAMES)
            GLib.timeout_add(FRAME_MS, self._step)
        else:
            self._schedule_burst()
        return False

    def _step(self):
        if self._left <= 0:
            self.frame = None
            self.queue_draw()
            self._schedule_burst()
            return False
        self._left -= 1
        word = list(WORD)
        if random.random() < 0.45:
            i = random.randrange(len(word))
            word[i] = random.choice(GLITCH_CHARS)
        self.frame = {
            'split': random.choice((1, 1, 2, 3)),
            'slices': [(random.uniform(0.1, 0.85), random.uniform(0.08, 0.25), random.choice((-4, -3, -2, 2, 3, 4)))
                       for _ in range(random.choice((0, 1, 1, 2)))],
            'hide': random.random() < 0.12,          # a frame where the mark blinks out
            'word': ''.join(word),
        }
        self.queue_draw()
        return True

    # --- drawing ---
    def _paint(self, cr, h, rgb, dx, word):
        """The mark at x=dx, then the word."""
        cr.save()
        cr.translate(dx, 0)
        s = h - 4                    # square size
        x0, y0 = 1.5, 2.0
        lw = max(1.4, s * 0.1)
        cr.set_source_rgb(*rgb)
        cr.set_line_width(lw)
        # outline with the bottom-right corner left open for the "1"
        cr.move_to(x0 + s, y0 + s * 0.62)
        cr.line_to(x0 + s, y0)
        cr.line_to(x0, y0)
        cr.line_to(x0, y0 + s)
        cr.line_to(x0 + s * 0.62, y0 + s)
        cr.stroke()
        cr.arc(x0 + s * 0.2, y0 + s * 0.22, s * 0.075, 0, 6.2832)
        cr.fill()
        # the "1" breaking out of the corner
        layout = PangoCairo.create_layout(cr)
        fd = Pango.FontDescription.from_string('DejaVu Serif Bold')
        fd.set_absolute_size(s * 1.05 * Pango.SCALE)
        layout.set_font_description(fd)
        layout.set_text('1', -1)
        _ink, logical = layout.get_pixel_extents()
        iw, ih = logical.width, logical.height
        cr.move_to(x0 + s - iw * 0.5, y0 + s - ih * 0.83)   # its flag breaks through the right edge
        PangoCairo.layout_path(cr, layout)
        cr.set_line_width(0.8)                                # a little extra weight at this size
        cr.fill_preserve()
        cr.stroke()
        # the word
        layout = PangoCairo.create_layout(cr)
        fd = Pango.FontDescription.from_string('%s Bold' % self.win.cfg['font'].get('family', 'Monospace'))
        fd.set_absolute_size(h * 0.56 * Pango.SCALE)
        layout.set_font_description(fd)
        layout.set_text(word, -1)
        _tw, th = layout.get_pixel_size()
        cr.move_to(x0 + s + 7, (h - th) / 2)
        PangoCairo.show_layout(cr, layout)
        cr.restore()

    def _draw(self, _w, cr):
        h = self.get_allocated_height()
        w = self.get_allocated_width()
        fg = _rgb(self.win.theme['fg'])
        bg = _rgb(self.win.theme['pane'])
        f = self.frame
        if not f:
            self._paint(cr, h, fg, 0, WORD)
            return False
        if f['hide']:
            return False
        # color-split copies behind the main one
        cr.push_group()
        self._paint(cr, h, SPLIT_A, -f['split'], f['word'])
        cr.pop_group_to_source()
        cr.paint_with_alpha(0.75)
        cr.push_group()
        self._paint(cr, h, SPLIT_B, f['split'], f['word'])
        cr.pop_group_to_source()
        cr.paint_with_alpha(0.75)
        self._paint(cr, h, fg, 0, f['word'])
        # shifted slices
        for top, height, shift in f['slices']:
            y, sh = int(top * h), max(2, int(height * h))
            cr.save()
            cr.rectangle(0, y, w, sh)
            cr.clip()
            cr.set_source_rgb(*bg)
            cr.paint()
            self._paint(cr, h, fg, shift, f['word'])
            cr.restore()
        return False
