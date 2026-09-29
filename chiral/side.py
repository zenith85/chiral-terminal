"""Shift+→ terminal columns: each press adds a plain shell to the right and focuses it.

All columns (the main terminal included) share the width equally. The focused one shows the normal
font size; the others drop a few points (`font.unfocused_drop`), so Ctrl+←/→ moves a "bigger text"
spotlight across them. `exit` or Ctrl+Shift+W closes a column; focus moves to its left neighbour.
"""
import os

from gi.repository import Gtk


class Column:
    """One terminal column to the right of the main terminal."""

    def __init__(self, win, sid, folder, team=False):
        from .window import framed
        self.win = win
        self.sid = sid
        self.team = team             # a locked team-session shell: sees only `folder`
        self.folder = os.path.abspath(folder or os.path.expanduser('~'))
        self.term = win.make_terminal()
        self.term.chiral_column = self
        self.frame = framed(self.term)
        if team:
            self.frame.get_style_context().add_class('team')
        self.term.connect('child-exited', lambda *_: win.close_column(self))

    def start(self):
        if not self.team:
            self.win.spawn(self.term, role='side', win=self.sid, cwd=self.folder)
            return
        from . import sandbox
        # a clean environment: nothing of the host's (API keys, sockets, history) goes inside
        env = ['PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
               'TERM=xterm-256color', 'COLORTERM=truecolor', 'LANG=%s' % os.environ.get('LANG', 'C.UTF-8'),
               'USER=team', 'CHIRAL_ROLE=team', 'CHIRAL_WIN=%d' % self.sid, 'CHIRAL_EVENTS=/dev/null',
               'PS1=\\[\\e[1;35m\\]team\\[\\e[0m\\]:\\[\\e[1;34m\\]\\w\\[\\e[0m\\]$ ']
        # VTE adds our variables on top of Chiral's own environment, so `env -i` wipes it first:
        # the sandbox then starts with exactly the list above and nothing else
        argv = ['/usr/bin/env', '-i'] + env + sandbox.argv(self.folder, self.win.runtime.rc)
        self.win.spawn(self.term, role='team', win=self.sid, cwd=self.folder, argv=argv, env=env)

    def number(self):
        return self.win.columns.index(self) + 1 if self in self.win.columns else 0
