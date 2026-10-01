"""Image files in a floating window: an "image" tab (the picture, fitted) and a "hex" tab.

The picture is scaled to fit (never blown up past 4x), centred, with a checkerboard under transparent
parts and a line with its size, format and file size. Click the tabs in the title bar or press
Ctrl+Tab to switch.
"""
import os

from gi.repository import GLib, Gdk, GdkPixbuf, Gtk

IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.ico', '.tif', '.tiff', '.xpm',
             '.tga', '.pnm', '.ppm', '.pgm'}
MAX_LOAD = 4096            # load big pictures at most this large (keeps memory small)
MAX_ZOOM = 4.0


def is_image(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXT:
        return True
    try:
        fmt = GdkPixbuf.Pixbuf.get_file_info(path)[0]
    except (GLib.Error, TypeError):
        return False
    return fmt is not None


def _human(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return ('%d %s' % (n, unit)) if unit == 'B' else ('%.1f %s' % (n, unit))
        n /= 1024.0


class ImageView(Gtk.DrawingArea):
    def __init__(self, win, path):
        super().__init__()
        self.win = win
        self.path = path
        self.pixbuf = None
        self.error = None
        self.info = ''
        self.set_can_focus(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect('draw', self._draw)
        self.connect('button-press-event', lambda *_: (self.grab_focus(), False)[1])
        self._load()

    def _load(self):
        try:
            fmt, w, h = GdkPixbuf.Pixbuf.get_file_info(self.path)
            self.pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(self.path, min(w or MAX_LOAD, MAX_LOAD),
                                                                  min(h or MAX_LOAD, MAX_LOAD), True)
            name = fmt.get_name().upper() if fmt else os.path.splitext(self.path)[1][1:].upper()
            self.info = '%d×%d · %s · %s' % (w, h, name, _human(os.path.getsize(self.path)))
        except (GLib.Error, OSError, TypeError) as e:
            self.error = getattr(e, 'message', str(e))
            self.info = 'cannot show this image: %s · see the hex tab' % self.error

    def _draw(self, area, cr):
        th = self.win.theme
        w, h = area.get_allocated_width(), area.get_allocated_height()
        bg = Gdk.RGBA()
        bg.parse(th['bg'])
        cr.set_source_rgb(bg.red, bg.green, bg.blue)
        cr.paint()
        info_h = 18
        avail_w, avail_h = w - 16, h - info_h - 12
        if self.pixbuf and avail_w > 10 and avail_h > 10:
            pw, ph = self.pixbuf.get_width(), self.pixbuf.get_height()
            scale = min(avail_w / pw, avail_h / ph, MAX_ZOOM)
            dw, dh = pw * scale, ph * scale
            x, y = (w - dw) / 2, 6 + (avail_h - dh) / 2
            if self.pixbuf.get_has_alpha():                      # checkerboard behind transparency
                cr.save()
                cr.rectangle(x, y, dw, dh)
                cr.clip()
                size = 8
                for i in range(int(dw // size) + 2):
                    for j in range(int(dh // size) + 2):
                        cr.set_source_rgb(*((0.42, 0.42, 0.44) if (i + j) % 2 else (0.32, 0.32, 0.34)))
                        cr.rectangle(x + i * size, y + j * size, size, size)
                        cr.fill()
                cr.restore()
            cr.save()
            cr.translate(x, y)
            cr.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
            cr.get_source().set_filter(1 if scale < 1 else 3)  # good for shrinking, crisp pixels when enlarged
            cr.paint()
            cr.restore()
        fg = Gdk.RGBA()
        fg.parse(th['dim'])
        cr.set_source_rgb(fg.red, fg.green, fg.blue)
        layout = self.create_pango_layout(self.info + ('' if self.error else '   ·   ctrl+tab: hex'))
        lw, lh = layout.get_pixel_size()
        cr.move_to(max(6, (w - lw) / 2), h - info_h + (info_h - lh) / 2 - 2)
        from gi.repository import PangoCairo
        PangoCairo.show_layout(cr, layout)
        return False


def add_image_tab(sub, path):
    """Turn a hex-viewer sub-window into two tabs: image (shown first) and hex."""
    view = ImageView(sub.win, path)
    view.chiral_sub = sub
    view.connect('focus-in-event', lambda *_: (sub.win.focus_sub(sub, grab=False), sub.win._mark_focused(sub), False)[2])
    stack = Gtk.Stack()
    sub.body_box.remove(sub.term)
    stack.add_named(view, 'image')
    stack.add_named(sub.term, 'hex')
    sub.body_box.pack_start(stack, True, True, 0)
    stack.show_all()
    stack.set_visible_child_name('image')
    sub.image_view, sub.tabs = view, stack

    buttons = {}
    for name in ('image', 'hex'):
        b = Gtk.Button(label=name)
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.set_can_focus(False)
        b.get_style_context().add_class('chiral-tab')
        b.connect('clicked', lambda _b, n=name: show_tab(sub, n))
        buttons[name] = b
    sub.tab_buttons = buttons
    sub.add_title_widget(buttons['hex'])
    sub.add_title_widget(buttons['image'])                     # inserted first: "image  hex  …  _ ×"
    _mark_tabs(sub)


def _mark_tabs(sub):
    current = sub.tabs.get_visible_child_name()
    for name, b in sub.tab_buttons.items():
        ctx = b.get_style_context()
        (ctx.add_class if name == current else ctx.remove_class)('active')


def show_tab(sub, name):
    sub.tabs.set_visible_child_name(name)
    _mark_tabs(sub)
    (sub.image_view if name == 'image' else sub.term).grab_focus()


def toggle_tab(sub):
    show_tab(sub, 'hex' if sub.tabs.get_visible_child_name() == 'image' else 'image')
