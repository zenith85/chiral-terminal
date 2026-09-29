"""Pick a font size so a sub-terminal of a given width shows about N columns."""
from gi.repository import Pango

_width_cache = {}


def desc(family, size):
    d = Pango.FontDescription.from_string(family)
    d.set_size(int(size * Pango.SCALE))
    return d


def char_width(widget, family, size):
    key = (family, size)
    if key not in _width_cache:
        layout = widget.create_pango_layout('M' * 40)
        layout.set_font_description(desc(family, size))
        _width_cache[key] = max(1.0, layout.get_pixel_size()[0] / 40.0)
    return _width_cache[key]


def char_height(widget, family, size):
    key = ('h', family, size)
    if key not in _width_cache:
        layout = widget.create_pango_layout('Mg')
        layout.set_font_description(desc(family, size))
        _width_cache[key] = max(1.0, float(layout.get_pixel_size()[1]))
    return _width_cache[key]


def fit(widget, width_px, font_cfg):
    lo = int(font_cfg.get('auto_min', 7))
    hi = max(lo, int(font_cfg.get('auto_max', 16)))
    cols = max(20, int(font_cfg.get('auto_columns', 80)))
    family = font_cfg.get('family', 'Monospace')
    for size in range(hi, lo - 1, -1):
        if width_px / char_width(widget, family, size) >= cols:
            return size
    return lo
