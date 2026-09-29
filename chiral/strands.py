"""Animated background: faint strands stretching from top to bottom, like a chiral network.

The strands mirror the folder the terminal is in: one strand per entry, thicker ones for folders
and thin ones for files (at most MAX_STRANDS, split in the same proportion for big folders). When
the folder changes, new strands fade in and extra ones fade out; the others stay where they are.
Everything is drawn in the text colour at a very low opacity, behind the text.
"""
import math
import random

MAX_STRANDS = 24
SEGMENTS = 22
KNOTS_PER_STRAND = 2
ALPHA = 0.075            # strands
KNOT_ALPHA = 0.16
LINK_ALPHA = 0.035
FADE_S = 1.2
GOLDEN = 0.6180339887


class StrandField:
    def __init__(self, seed):
        self.seed = seed
        self.strands = []                    # alive and fading strands
        self.links = []
        self.counts = None
        self.set_counts(0, 3, 0.0)           # until the folder is known: a few thin strands

    # ---------- which strands exist ----------
    def _make(self, index, kind, born):
        rnd = random.Random(self.seed * 1009 + index * 31 + (7 if kind == 'dir' else 0))
        folder = kind == 'dir'
        return {
            'index': index, 'kind': kind, 'born': born, 'dying': None,
            # spread by the golden ratio: adding a strand never moves the existing ones
            'x': 0.04 + 0.92 * ((index * GOLDEN + self.seed * 0.137) % 1.0),
            'amp1': rnd.uniform(0.015, 0.045), 'k1': rnd.uniform(1.2, 2.6), 'w1': rnd.uniform(0.10, 0.22),
            'amp2': rnd.uniform(0.006, 0.02), 'k2': rnd.uniform(4.0, 7.0), 'w2': rnd.uniform(0.25, 0.45),
            'phase': rnd.uniform(0, 2 * math.pi),
            'width': rnd.uniform(1.2, 2.3) if folder else rnd.uniform(0.35, 1.0),
            'wk': rnd.uniform(1.5, 4.5), 'ww': rnd.uniform(0.08, 0.3), 'wphase': rnd.uniform(0, 2 * math.pi),
            'knots': [(rnd.uniform(0, 1), rnd.uniform(0.015, 0.04)) for _ in range(KNOTS_PER_STRAND)],
        }

    def set_counts(self, dirs, files, now):
        """Show `dirs` folder strands and `files` file strands (scaled down to MAX_STRANDS)."""
        total = dirs + files
        if total > MAX_STRANDS:
            d = max(1 if dirs else 0, round(MAX_STRANDS * dirs / total))
            dirs, files = d, MAX_STRANDS - d
        if dirs + files == 0:
            files = 1                                           # an empty folder: one faint strand
        if self.counts == (dirs, files):
            return
        self.counts = (dirs, files)
        wanted = ['dir'] * dirs + ['file'] * files
        alive = [s for s in self.strands if s['dying'] is None]
        for i, kind in enumerate(wanted):
            if i < len(alive) and alive[i]['kind'] == kind:
                continue
            if i < len(alive):
                alive[i]['dying'] = now
            self.strands.append(self._make(i, kind, now))
        for s in alive[len(wanted):]:
            s['dying'] = now
        self._relink()

    def _relink(self):
        live = sorted((s for s in self.strands if s['dying'] is None), key=lambda s: s['x'])
        rnd = random.Random(self.seed * 7 + len(live))
        self.links = [(a['index'], b['index'], rnd.uniform(0.1, 0.9), rnd.uniform(0.08, 0.18))
                      for a, b in zip(live, live[1:]) if rnd.random() < 0.6]

    # ---------- geometry ----------
    @staticmethod
    def _x(s, y, t):
        return (s['x']
                + s['amp1'] * math.sin(s['k1'] * y * math.pi + s['w1'] * t + s['phase'])
                + s['amp2'] * math.sin(s['k2'] * y * math.pi - s['w2'] * t + s['phase'] * 1.7))

    @staticmethod
    def _thickness(s, y, t):
        wave = 0.5 + 0.5 * math.sin(s['wk'] * math.pi * y + s['ww'] * t + s['wphase'])
        ripple = 0.5 + 0.5 * math.sin(3.1 * s['wk'] * math.pi * y - 0.5 * s['ww'] * t)
        return max(0.15, s['width'] * (0.15 + 1.25 * wave * (0.7 + 0.3 * ripple)))

    @staticmethod
    def _presence(s, t):
        """0..1: fading in after birth, fading out after it was removed."""
        p = min(1.0, max(0.0, (t - s['born']) / FADE_S)) if s['born'] else 1.0
        if s['dying'] is not None:
            p *= max(0.0, 1.0 - (t - s['dying']) / FADE_S)
        return p

    # ---------- drawing ----------
    def draw(self, cr, w, h, t, rgb):
        if w < 20 or h < 20:
            return
        self.strands = [s for s in self.strands if s['dying'] is None or t - s['dying'] < FADE_S]
        r, g, b = rgb
        busy = max(0.6, min(1.0, 10.0 / max(1, len(self.strands))))   # many strands: each a bit fainter
        cr.save()
        cr.set_line_cap(1)
        by_index = {}
        for s in self.strands:
            p = self._presence(s, t) * busy
            if p <= 0:
                continue
            if s['dying'] is None:
                by_index[s['index']] = s
            pts = [(self._x(s, i / SEGMENTS, t) * w, (i / SEGMENTS) * h) for i in range(SEGMENTS + 1)]
            for i in range(SEGMENTS):
                (x0, y0), (x1, y1) = pts[i], pts[i + 1]
                thick = self._thickness(s, (i + 0.5) / SEGMENTS, t)
                cr.set_source_rgba(r, g, b, p * ALPHA * (0.55 + 0.45 * min(1.0, thick / 1.5)))
                cr.set_line_width(thick)
                cr.move_to(x0, y0 - (2 if i == 0 else 0))
                cr.line_to(x1, y1 + (2 if i == SEGMENTS - 1 else 0))
                cr.stroke()
            for start, speed in s['knots']:
                y = (start + speed * t) % 1.0
                cr.set_source_rgba(r, g, b, p * KNOT_ALPHA * math.sin(y * math.pi))
                cr.arc(self._x(s, y, t) * w, y * h, 1.2 + self._thickness(s, y, t), 0, 2 * math.pi)
                cr.fill()
        for ia, ib, y0, span in self.links:
            a, b2 = by_index.get(ia), by_index.get(ib)
            if not a or not b2:
                continue
            p = min(self._presence(a, t), self._presence(b2, t)) * busy
            y = (y0 + 0.03 * math.sin(0.2 * t + ia)) % 1.0
            breath = 0.5 + 0.5 * math.sin(0.35 * t + ia * 1.3)
            cr.set_source_rgba(r, g, b, p * LINK_ALPHA * (0.4 + 0.6 * breath))
            cr.set_line_width(0.6)
            xa, xb = self._x(a, y, t) * w, self._x(b2, y + span, t) * w
            cr.move_to(xa, y * h)
            cr.curve_to(xa + (xb - xa) * 0.3, (y + span * 0.1) * h, xb - (xb - xa) * 0.3, (y + span * 0.9) * h,
                        xb, (y + span) * h)
            cr.stroke()
        cr.restore()
