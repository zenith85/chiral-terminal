"""Terminal hex viewer: `python3 -m chiral.hexview FILE`.

Keys: arrows/j/k/h/l move · PgUp/PgDn · Home/End · g go to offset · / find (hex bytes or "text")
      n next match · q quit
Bytes are colored by kind: 00 dim, printable green, ff yellow, other plain.
"""
import curses
import mmap
import os
import sys

COLS = 16


def _classes():
    curses.start_color()
    curses.use_default_colors()
    pairs = {'zero': curses.COLOR_BLACK + 8 if curses.COLORS >= 16 else curses.COLOR_WHITE,
             'print': curses.COLOR_GREEN, 'ff': curses.COLOR_YELLOW, 'off': curses.COLOR_BLUE,
             'ascii': curses.COLOR_CYAN, 'bar': curses.COLOR_BLACK}
    out = {}
    for i, (name, color) in enumerate(pairs.items(), 1):
        if name == 'bar':
            curses.init_pair(i, curses.COLOR_BLACK, curses.COLOR_WHITE)
        else:
            curses.init_pair(i, color, -1)
        out[name] = curses.color_pair(i)
    if curses.COLORS < 16:
        out['zero'] |= curses.A_DIM
    return out


def _kind(b):
    if b == 0:
        return 'zero'
    if b == 0xFF:
        return 'ff'
    if 32 <= b < 127:
        return 'print'
    return None


def _parse_needle(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in '"\'':
        return text[1:-1].encode()
    try:
        return bytes.fromhex(text)
    except ValueError:
        return text.encode()


class Viewer:
    def __init__(self, scr, path):
        self.scr = scr
        self.path = path
        self.size = os.path.getsize(path)
        self.f = open(path, 'rb')
        self.data = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ) if self.size else b''
        self.top = 0          # first row shown
        self.cur = 0          # cursor byte offset
        self.msg = ''
        self.needle = b''
        self.c = _classes()

    def rows_visible(self):
        return max(1, self.scr.getmaxyx()[0] - 2)

    def total_rows(self):
        return max(1, (self.size + COLS - 1) // COLS)

    def prompt(self, label):
        h, w = self.scr.getmaxyx()
        curses.echo()
        curses.curs_set(1)
        self.scr.move(h - 1, 0)
        self.scr.clrtoeol()
        self.scr.addstr(h - 1, 0, label)
        try:
            text = self.scr.getstr(h - 1, len(label), max(1, w - len(label) - 1)).decode(errors='replace')
        except curses.error:
            text = ''
        curses.noecho()
        curses.curs_set(0)
        return text

    def goto(self, off):
        self.cur = max(0, min(off, max(0, self.size - 1)))
        row = self.cur // COLS
        if row < self.top or row >= self.top + self.rows_visible():
            self.top = max(0, row - self.rows_visible() // 3)

    def find(self, start):
        if not self.needle or not self.size:
            return
        i = self.data.find(self.needle, start)
        if i < 0:
            i = self.data.find(self.needle, 0)
            self.msg = 'wrapped' if i >= 0 else 'not found: %s' % self.needle.hex(' ')
        else:
            self.msg = 'found at 0x%x' % i
        if i >= 0:
            self.goto(i)

    def draw(self):
        s = self.scr
        s.erase()
        h, w = s.getmaxyx()
        title = ' %s  %d bytes  %s ' % (os.path.basename(self.path), self.size, os.path.dirname(os.path.abspath(self.path)))
        s.addnstr(0, 0, title.ljust(w), w - 1, self.c['bar'])
        for r in range(self.rows_visible()):
            row = self.top + r
            base = row * COLS
            if base >= self.size and not (self.size == 0 and row == 0):
                break
            y = r + 1
            try:
                s.addstr(y, 0, '%08x: ' % base, self.c['off'])
                x = 10
                chunk = self.data[base:base + COLS]
                for i, b in enumerate(chunk):
                    attr = self.c.get(_kind(b), 0)
                    if base + i == self.cur:
                        attr |= curses.A_REVERSE
                    s.addstr(y, x, '%02x' % b, attr)
                    x += 3 + (1 if i == 7 else 0)
                x = 10 + COLS * 3 + 2
                text = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                if x + len(text) < w:
                    s.addstr(y, x, text, self.c['ascii'])
            except curses.error:
                pass
        b = self.data[self.cur] if self.size else 0
        chunk = bytes(self.data[self.cur:self.cur + 4]) if self.size else b''
        info = ' off 0x%x (%d)  u8=%d' % (self.cur, self.cur, b)
        if len(chunk) >= 2:
            info += '  u16le=%d' % int.from_bytes(chunk[:2], 'little')
        if len(chunk) == 4:
            info += '  u32le=%d  u32be=%d' % (int.from_bytes(chunk, 'little'), int.from_bytes(chunk, 'big'))
        hint = '  g goto  / find  n next  q quit'
        line = (info + ('  · ' + self.msg if self.msg else '') + hint)[:w - 1]
        try:
            s.addnstr(h - 1, 0, line.ljust(w - 1), w - 1, self.c['bar'])
        except curses.error:
            pass
        s.refresh()

    def run(self):
        curses.curs_set(0)
        self.scr.keypad(True)
        while True:
            self.draw()
            k = self.scr.getch()
            self.msg = ''
            page = self.rows_visible() * COLS
            if k in (ord('q'), 27):
                return
            elif k in (curses.KEY_DOWN, ord('j')):
                self.goto(self.cur + COLS)
            elif k in (curses.KEY_UP, ord('k')):
                self.goto(self.cur - COLS)
            elif k in (curses.KEY_RIGHT, ord('l')):
                self.goto(self.cur + 1)
            elif k in (curses.KEY_LEFT, ord('h')):
                self.goto(self.cur - 1)
            elif k in (curses.KEY_NPAGE, ord(' ')):
                self.goto(self.cur + page)
            elif k == curses.KEY_PPAGE:
                self.goto(self.cur - page)
            elif k in (curses.KEY_HOME, ord('0')):
                self.goto(0)
            elif k in (curses.KEY_END, ord('G')):
                self.goto(self.size - 1)
            elif k == ord('g'):
                text = self.prompt('go to offset (hex, or decimal with #): ')
                try:
                    self.goto(int(text[1:]) if text.startswith('#') else int(text, 16))
                except ValueError:
                    self.msg = 'not an offset: %s' % text
            elif k == ord('/'):
                text = self.prompt('find (hex bytes like 7f 45, or "text"): ')
                if text:
                    self.needle = _parse_needle(text)
                    self.find(self.cur + 1)
            elif k == ord('n'):
                self.find(self.cur + 1)
            elif k == curses.KEY_RESIZE:
                self.goto(self.cur)


def main():
    if len(sys.argv) != 2:
        print('usage: python3 -m chiral.hexview FILE')
        return 2
    path = sys.argv[1]
    if not os.path.isfile(path):
        print('hexview: not a file: %s' % path)
        return 1
    os.environ.setdefault('ESCDELAY', '25')
    curses.wrapper(lambda scr: Viewer(scr, path).run())
    return 0


if __name__ == '__main__':
    sys.exit(main())
