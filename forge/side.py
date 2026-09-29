"""Shift+→ terminal columns: each press adds a plain shell to the right and focuses it.

All columns (the main terminal included) share the width equally. The focused one shows the normal
font size; the others drop a few points (`font.unfocused_drop`), so Ctrl+←/→ moves a "bigger text"
spotlight across them. `exit` or Ctrl+Shift+W closes a column; focus moves to its left neighbour.
"""
import os

from gi.repository import Gtk


class Column:
    """One terminal column to the right of the main terminal."""

    def __init__(self, win, sid, folder):
        from .window import framed
        self.win = win
        self.sid = sid
        self.folder = os.path.abspath(folder or os.path.expanduser('~'))
        self.term = win.make_terminal()
        self.term.forge_column = self
        self.frame = framed(self.term)
        self.term.connect('child-exited', lambda *_: win.close_column(self))

    def start(self):
        self.win.spawn(self.term, role='side', win=self.sid, cwd=self.folder)

    def number(self):
        return self.win.columns.index(self) + 1 if self in self.win.columns else 0
