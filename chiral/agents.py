"""AI agents: Claude Code in floating sub-terminals that watch what you do.

Shift+↑ → "AI agent" opens one (Claude or Codex, already running) in the folder of the terminal you
are in. It starts through bash, so tools installed with nvm are found even when Chiral was started
from a desktop shortcut. Every command you finish
in any terminal is written to a context file the agents can read (with the output of failed ones).
When a command fails and `claude.watch = "auto"`, the agent you used last explains it — never while
you are typing in it. `#question` in the command bar and Ctrl+Shift+E go to that agent too, opening
one if there is none.
"""
import os
import shlex
import time

from gi.repository import GLib

SKIP_STATUS = {0, 130, 148}      # success, Ctrl+C, Ctrl+Z
AUTO_GAP_S = 15
STARTUP_S = 4

PROMPT = (
    "You are an AI agent running inside Chiral, a terminal on the user's Linux desktop, in a floating "
    "window above their shells. Chiral appends every command the user finishes in any of their "
    "terminals (window, exit status, cwd, and the last lines of output) to {context}. Read that file "
    "whenever the user refers to what they are doing, what just happened, or a failure. Be brief. Do "
    "not edit files or run commands unless the user asks."
)


class AgentManager:
    def __init__(self, win):
        self.win = win
        self.agents = []             # SubWindows running Claude, oldest first
        self.last_used = None
        self.last_auto = 0
        self.last_failure = None

    # --- opening ---
    def spawn(self, folder=None, kind=None):
        win = self.win
        folder = os.path.abspath(folder or win.cwd)
        acfg = win.cfg['claude']
        kind = kind or acfg.get('default_agent', 'claude')
        if kind == 'codex':
            cmd = acfg.get('codex_command', 'codex')
            launch = 'exec %s' % cmd
        elif kind == 'local':
            model = acfg.get('local_model') or 'llama3.2:3b'
            cmd = 'ollama'
            launch = 'exec ollama run %s' % shlex.quote(model)
        else:
            kind = 'claude'
            cmd = acfg.get('command', 'claude')
            launch = 'exec %s --append-system-prompt "$CHIRAL_AGENT_PROMPT"' % cmd
        tool = shlex.split(cmd)[0] if cmd.strip() else kind
        # an interactive bash loads ~/.bashrc (nvm, PATH), then becomes the agent
        script = ('if command -v %s >/dev/null 2>&1; then %s; fi; '
                  'printf "\\nchiral: %s was not found in your shell PATH.\\n'
                  'Install it, or set it under [claude] in chiral settings. This window is a normal shell now.\\n\\n"; '
                  'exec bash -i' % (shlex.quote(tool), launch, tool))
        argv = ['/bin/bash', '--rcfile', win.runtime.rc, '-i', '-c', script]
        env = {'CHIRAL_AGENT_PROMPT': PROMPT.format(context=win.runtime.context)}
        title = '%s · %s' % (kind, os.path.basename(folder) or folder)
        sub = win.new_sub(title, argv=argv, cwd=folder, agent=True, extra_env=env)
        sub.agent_kind = kind
        sub.agent_started = time.time()
        area_w, area_h = win.workspace_size()     # agents open on the right, tall, like a chat
        n = len(self.agents)
        sub.place(int(area_w * 0.46) - n * 30, 24 + n * 30, int(area_w * 0.52), int(area_h * 0.86))
        self.agents.append(sub)
        self.last_used = sub
        win.aware.update_right()
        return sub

    def forget(self, sub):
        if sub in self.agents:
            self.agents.remove(sub)
        if self.last_used is sub:
            self.last_used = self.agents[-1] if self.agents else None

    def touch(self, sub):
        if sub in self.agents:
            self.last_used = sub

    def current(self):
        return self.last_used if self.last_used in self.agents else (self.agents[-1] if self.agents else None)

    # --- talking ---
    def send(self, text, sub=None):
        """Type a message into an agent and submit it (waits for Claude to finish starting)."""
        sub = sub or self.current() or self.spawn(self.win.focused_folder())
        if not sub.get_visible():
            self.win.show_sub(sub)
        wait = STARTUP_S - (time.time() - getattr(sub, 'agent_started', 0))
        data = (text.replace('\n', ' ') + '\r').encode()

        def feed():
            if sub not in self.agents:
                return False
            try:
                sub.term.feed_child(data)
            except TypeError:
                sub.term.feed_child_binary(data)
            return False
        if wait > 0:
            GLib.timeout_add(int(wait * 1000), feed)
        else:
            feed()

    def on_command(self, win_label, status, command):
        if status in SKIP_STATUS or not command.strip():
            return
        self.last_failure = (status, command.strip()[:60], win_label)
        self.win.aware.update_right()
        sub = self.current()
        if self.win.cfg['claude'].get('watch', 'auto') != 'auto' or sub is None or not sub.get_visible():
            return
        if sub.term.has_focus() or time.time() - self.last_auto < AUTO_GAP_S:
            return
        self.last_auto = time.time()
        self.explain(sub)

    def explain(self, sub=None):
        if not self.last_failure:
            self.win.toast('no failed command to explain yet')
            return
        status, command, win_label = self.last_failure
        self.send('[chiral] In %s, `%s` just exited with status %d. Its output is at the end of %s. '
                  'In 2-4 lines: what went wrong and how to fix it.'
                  % (win_label, command, status, self.win.runtime.context), sub)

    def summary(self):
        if not self.agents:
            return ''
        mark = '✗' if self.last_failure else '●'
        return 'agent%s %s' % ('s ×%d' % len(self.agents) if len(self.agents) > 1 else '', mark)
